"""Loopback-only local review app, bound to one repository selected by the CLI."""
import html
import json
import os
import secrets
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import yaml
from pydantic import ValidationError
from . import __version__, baseline, configuration, instructions
from .engine import scan, exit_code
from .quickcheck import check as quick_check
from .discovery import PARSER_JAVA, discover
from .projects import prepare as prepare_project
from .reporters import dashboard, sarif

def user_error(error):
    if isinstance(error, ValidationError):
        return '\n'.join(
            ('.'.join(str(part) for part in item['loc']) + ': ' if item['loc'] else '')
            + item['msg'].removeprefix('Value error, ')
            for item in error.errors(include_url=False, include_input=False))
    return str(error)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self):
        for child, thread in getattr(self, 'children', []):
            child.shutdown()
            child.server_close()
            thread.join(timeout=5)
        self.children = []
        super().server_close()
        temporary = getattr(self, 'temporary', None)
        if temporary:
            temporary.cleanup()
            self.temporary = None


def make_server(root, port=0, *, quick=False, project=None):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Repository must be a directory')
    token = secrets.token_urlsafe(32)
    lock = threading.RLock()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *args):
            pass

        def send(self, value, status=200, content_type='application/json'):
            body = json.dumps(value).encode() if content_type == 'application/json' else value.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, api=False):
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected:
                self.send({'error': 'Unexpected host'}, 403)
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                self.send({'error': 'Cross-origin request rejected'}, 403)
                return False
            if api and not secrets.compare_digest(self.headers.get('X-AgentAccord-Token', ''), token):
                self.send({'error': 'This tab has no session token. Open the full link printed by agentaccord serve, '
                                       'including the #token=… part; the address bar hides it after the first load.'}, 403)
                return False
            return True

        def do_GET(self):
            route = urlsplit(self.path).path
            if not self.allowed(route.startswith('/api/')):
                return
            if route in ('/', '/app.js', '/style.css'):
                name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[route]
                mime = {'/': 'text/html', '/app.js': 'text/javascript', '/style.css': 'text/css'}[route]
                self.send((Path(__file__).parent / 'web' / name).read_text(), content_type=mime)
                return
            if route == '/api/state':
                try:
                    policy = configuration.load(root, optional=True)
                    self.send(dict(version=__version__, java_parser=PARSER_JAVA, workspace_mode="quick" if quick else "repository", project=project or dict(kind="local", label=str(root), temporary=False), repository=str(root), name="Local text check" if quick else root.name, policy=policy.model_dump(), rules=policy.catalog(),
                        discovery=discover(root), guidance=instructions.guidance(policy.active(), policy.catalog())))
                except (ValueError, OSError, yaml.YAMLError, RecursionError) as error:
                    self.send({'error': user_error(error)}, 400)
                return
            self.send({'error': 'Not found'}, 404)

        def do_POST(self):
            with lock:
                self.post()

        def post(self):
            if not self.allowed(True):
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send({'error': 'JSON required'}, 415)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                limit = 2_500_000 if urlsplit(self.path).path == '/api/quick-check' else 32_768
                if not 0 < length <= limit:
                    raise ValueError(f'Request must contain 1–{limit} bytes')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected a JSON object')
                route = urlsplit(self.path).path
                if route == '/api/quick-check':
                    self.send(quick_check(body))
                elif route == '/api/open-project':
                    if len(self.server.children) >= 5:
                        raise ValueError('This workspace has opened five projects. Restart the app to release them before opening more.')
                    selected, temporary, metadata = prepare_project(body)
                    try:
                        # Bound discovery and policy validation before handing the workspace to the user.
                        discover(selected)
                        configuration.load(selected, optional=True)
                        child = make_server(selected, project=metadata)
                    except BaseException:
                        if temporary:
                            temporary.cleanup()
                        raise
                    child.temporary = temporary
                    thread = threading.Thread(target=child.serve_forever, daemon=True)
                    self.server.children.append((child, thread))
                    thread.start()
                    self.send(dict(url=child.url, project=metadata, repository=str(selected)))
                elif route == '/api/policy':
                    policy = configuration.Policy.model_validate(body)
                    configuration.save(root, policy)
                    self.send({'saved': True})
                elif route == '/api/preview':
                    # Draft policy is validated and scanned, never saved or baselined.
                    policy = configuration.Policy.model_validate(body)
                    report = scan(root, policy.active(), policy.exclude, policy.catalog(),
                                  policy.examples, capture_scope=True, java_version=policy.java.version)
                    self.send(dict(files=report['scope_files'], approved_rules=report['approved_rules'],
                                   analyzed_files=report['analyzed_files'], skipped=report['skipped'],
                                   excluded_files=report['excluded_files'], example_files=report['example_files'],
                                   counter_example_files=report['counter_example_files']))
                elif route in ('/api/check', '/api/export'):
                    policy = configuration.load(root)
                    report = baseline.apply(scan(root, policy.active(), policy.exclude, policy.catalog(), policy.examples,
                                                     java_version=policy.java.version), root)
                    if route == '/api/export':
                        fmt = body.get('format', 'json')
                        if fmt not in {'json', 'sarif', 'html'}:
                            raise ValueError('Unknown export format')
                        value = dashboard(report) if fmt == 'html' else json.dumps(sarif(report) if fmt == 'sarif' else report, indent=2)
                        self.send(dict(content=value, format=fmt))
                    else:
                        self.send(dict(report=report, exit_code=exit_code(report)))
                elif route == '/api/guidance':
                    policy = configuration.load(root)
                    if not policy.active():
                        raise ValueError('Approve at least one rule before writing guidance')
                    changed = instructions.sync(root, policy.active(), policy.catalog())
                    self.send(dict(changed=changed))
                else:
                    self.send({'error': 'Not found'}, 404)
            except (ValueError, OSError, yaml.YAMLError, RecursionError) as error:
                self.send({'error': user_error(error)}, 400)
    server = LocalServer(('127.0.0.1', port), Handler)
    # The fragment never reaches HTTP logs; the app moves it into per-tab memory.
    server.url = f'http://127.0.0.1:{server.server_port}/#token={token}'
    server.token = token
    server.children = []
    server.temporary = None
    return server


def can_open_browser():
    # Never fall back to a text-mode browser in SSH sessions, CI, or redirected output.
    if not sys.stdout.isatty():
        return False
    return not sys.platform.startswith('linux') or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def open_browser(url):
    """Open the app through an owner-only redirect file, so the token never appears in a process list."""
    descriptor, name = tempfile.mkstemp(prefix='agentaccord-', suffix='.html')
    path = Path(name)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        target = html.escape(url)
        handle.write(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={target}">'
                     f'<title>AgentAccord</title><a href="{target}">Open AgentAccord</a>')
    try:
        if webbrowser.open(path.as_uri()):
            return path
    except webbrowser.Error:
        pass
    path.unlink(missing_ok=True)
    return None


def serve(root, port, *, quick=False, browser=True):
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    server = make_server(root, port, quick=quick)
    print(f'AgentAccord local app: {server.url}', flush=True)
    launcher = open_browser(server.url) if browser and can_open_browser() else None
    if launcher:
        print('Opened in your default browser. Use the link above in other browsers.', flush=True)
    print(f'Repository: {root}\nPress Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if launcher:
            launcher.unlink(missing_ok=True)
