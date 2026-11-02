"""Loopback-only local review app, bound to one repository selected by the CLI."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import yaml
from . import configuration, instructions
from .engine import scan, exit_code
from .rules import RULES
from .discovery import discover
from .reporters import dashboard, sarif


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True


def make_server(root, port=0):
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
            if api and not secrets.compare_digest(self.headers.get('X-AgentContract-Token', ''), token):
                self.send({'error': 'Session token required'}, 403)
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
                    self.send(dict(repository=str(root), name=root.name, policy=policy.model_dump(), rules=RULES,
                        discovery=discover(root), guidance=instructions.guidance(policy.active())))
                except (ValueError, OSError, yaml.YAMLError, RecursionError) as error:
                    self.send({'error': str(error)}, 400)
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
                if not 0 < length <= 32_768:
                    raise ValueError('Request must contain 1–32768 bytes')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected a JSON object')
                route = urlsplit(self.path).path
                if route == '/api/policy':
                    policy = configuration.Policy.model_validate(body)
                    configuration.save(root, policy)
                    self.send({'saved': True})
                elif route in ('/api/check', '/api/export'):
                    policy = configuration.load(root)
                    report = scan(root, policy.active())
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
                    changed = instructions.sync(root, policy.active())
                    self.send(dict(changed=changed))
                else:
                    self.send({'error': 'Not found'}, 404)
            except (ValueError, OSError, yaml.YAMLError, RecursionError) as error:
                self.send({'error': str(error)}, 400)
    server = LocalServer(('127.0.0.1', port), Handler)
    # The fragment never reaches HTTP logs; the app moves it into per-tab memory.
    server.url = f'http://127.0.0.1:{server.server_port}/#token={token}'
    server.token = token
    return server


def serve(root, port):
    if not 0 <= port <= 65535:
        raise ValueError('Port must be between 0 and 65535')
    server = make_server(root, port)
    print(f'AgentContract local app: {server.url}', flush=True)
    print(f'Repository: {root}\nPress Ctrl+C to stop.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
