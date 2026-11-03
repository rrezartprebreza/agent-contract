"""Explicit project selection and bounded public GitHub snapshots. Never runs Git or code."""
import io
import os
import posixpath
import re
import stat
import ssl
import certifi
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr

MAX_DOWNLOAD = 20_000_000
MAX_EXPANDED = 50_000_000
MAX_ENTRIES = 10_000
MAX_LINK_TARGET = 4096
# Links that would leave the snapshot are recreated pointing here instead: a name that
# never exists, so the link is broken, cannot reach host files, and analysis that needs
# it is reported as incomplete -- the same outcome as a local clone.
OUTSIDE_LINK = '.agentaccord-link-target-outside-snapshot'


class ProjectRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['local', 'github']
    location: StrictStr = Field(min_length=1, max_length=2000)


def github_repository(location):
    url = urlsplit(location.strip())
    if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment
            or not re.fullmatch(r'/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+/?', url.path)):
        raise ValueError('Use a public repository URL: https://github.com/owner/repository (no credentials, branch path, or query)')
    owner, repo = url.path.strip('/').split('/')
    repo = repo.removesuffix('.git')
    if not repo or repo in {'.', '..'}:
        raise ValueError('Invalid repository name')
    return owner + '/' + repo


class GitHubRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != 'https' or url.netloc not in {'api.github.com', 'codeload.github.com'}:
            raise ValueError('GitHub redirected outside the supported archive hosts')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(repository):
    request = Request('https://api.github.com/repos/' + repository + '/zipball',
                      headers={'User-Agent': 'AgentAccord', 'Accept': 'application/vnd.github+json'})
    start = time.monotonic()
    try:
        context = ssl.create_default_context()
        context.load_verify_locations(certifi.where())
        with build_opener(GitHubRedirects(), HTTPSHandler(context=context)).open(request, timeout=20) as response:
            chunks, size = [], 0
            while True:
                if time.monotonic() - start > 60:
                    raise ValueError('GitHub snapshot download exceeded 60 seconds')
                chunk = response.read(65536)
                if not chunk:
                    return b''.join(chunks)
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError('GitHub snapshot exceeds the 20 MB download limit; open a local clone instead')
                chunks.append(chunk)
    except HTTPError as error:
        raise ValueError(f'GitHub returned HTTP {error.code}. Use an accessible public repository, or open a local clone for private repositories. GitHub rate limits may also apply.') from error
    except (URLError, TimeoutError) as error:
        raise ValueError('Could not download the GitHub snapshot. Check connectivity or open a local clone.') from error


def unpack(data, root):
    """Validate the complete manifest before writing anything. Regular files and folders are
    extracted; symbolic links are recreated last and never followed (see OUTSIDE_LINK).
    Returns the number of links and how many of them pointed outside the snapshot."""
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Archive exceeds 20 MB')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ENTRIES:
                raise ValueError('Snapshot must contain between 1 and 10,000 entries')
            total, prefix, paths, plan, links = 0, None, set(), [], []
            for entry in entries:
                name = entry.filename.rstrip('/')
                parts = name.split('/')
                if (not name or entry.filename.startswith('/') or '\\' in name or ':' in name
                        or any(p in {'', '.', '..'} for p in parts)
                        or any(ord(c) < 32 for c in name)):
                    raise ValueError('Snapshot contains an unsafe path')
                if prefix is None:
                    prefix = parts[0]
                if parts[0] != prefix:
                    raise ValueError('Snapshot must have one root folder')
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if mode not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK} or entry.flag_bits & 1:
                    raise ValueError('Snapshots with special files or encrypted entries require a local clone')
                if len(parts) == 1:
                    if not entry.is_dir():
                        raise ValueError('Snapshot root must be a folder')
                    continue
                relative = '/'.join(parts[1:])
                key = relative.casefold()
                if key in paths:
                    raise ValueError('Snapshot contains duplicate or case-colliding paths')
                paths.add(key)
                total += entry.file_size
                if total > MAX_EXPANDED:
                    raise ValueError('Snapshot exceeds 50 MB expanded; open a local clone instead')
                if mode == stat.S_IFLNK:
                    if entry.is_dir() or entry.file_size > MAX_LINK_TARGET:
                        raise ValueError('Snapshot contains an invalid symbolic link')
                    links.append((entry, relative))
                else:
                    plan.append((entry, root.joinpath(*parts[1:])))
            # Nothing may be written through a link: no entry can live underneath a link path.
            link_paths = {relative.casefold() for _, relative in links}
            for key in paths:
                if any(key.startswith(link + '/') for link in link_paths):
                    raise ValueError('Snapshot contains an entry inside a symbolic link')
            for entry, target in plan:
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open('xb') as output:
                        written = 0
                        while chunk := source.read(65536):
                            written += len(chunk)
                            if written > entry.file_size:
                                raise ValueError('Archive entry exceeds its declared size')
                            output.write(chunk)
            outside = 0
            for entry, relative in links:
                try:
                    target = archive.read(entry).decode('utf-8')
                except UnicodeDecodeError as error:
                    raise ValueError('Snapshot contains an invalid symbolic link') from error
                if not target or any(ord(c) < 32 for c in target) or '\\' in target:
                    raise ValueError('Snapshot contains an invalid symbolic link')
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), target))
                if target.startswith('/') or resolved == '..' or resolved.startswith('../'):
                    target, outside = OUTSIDE_LINK, outside + 1
                path = root.joinpath(*relative.split('/'))
                path.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(target, path)
            return dict(links=len(links), outside_links=outside)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
        raise ValueError('GitHub did not return a supported ZIP snapshot') from error


def prepare(body):
    request = ProjectRequest.model_validate(body)
    if request.kind == 'local':
        path = Path(request.location.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError('Enter an absolute local folder path')
        root = path.resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Select a folder, not a file')
        return root, None, dict(kind='local', label=str(root), temporary=False)
    repository = github_repository(request.location)
    temporary = TemporaryDirectory(prefix='agentaccord-github-')
    root = Path(temporary.name) / repository.split('/')[1]
    root.mkdir()
    try:
        extracted = unpack(download(repository), root)
    except BaseException:
        temporary.cleanup()
        raise
    note = ('Default-branch snapshot. No history, submodule checkout, or Git LFS download. '
            'Changes stay in this temporary copy and disappear when the app stops.')
    if extracted['links']:
        note += (f" {extracted['links']} symbolic link(s) kept as links and never followed"
                 + (f"; {extracted['outside_links']} pointed outside the snapshot and are left broken." if extracted['outside_links'] else '.'))
    return root, temporary, dict(kind='github', label='https://github.com/' + repository,
                                 temporary=True, note=note, links=extracted['links'],
                                 outside_links=extracted['outside_links'])
