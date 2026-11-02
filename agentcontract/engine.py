"""Shared analysis engine for CLI and local app. Never runs repository code."""
import hashlib
import re
from . import java_checks, python_checks, instructions
from .rules import RULES

EXCLUDED = {'.git', 'node_modules', 'target', 'build', 'dist', '.venv', 'venv', '__pycache__', '.idea'}
LIMITATIONS = [
 'Java resolves annotations from explicit imports, qualified names, and Java scoping rules; ambiguous wildcard/same-package names and import-free snippets are reported as incomplete. Custom meta-annotations and cross-file type resolution are unsupported.',
 'Instruction checks recognize direct affirmative patterns only. Fenced examples, block quotes, indented code, and HTML comments are excluded; prose semantics and instruction precedence are not interpreted.',
 'Approved policies apply to the entire selected repository. No inferred rule becomes blocking without approval.',
 'Python checks cover literal list/dict/set defaults and missing function annotations, exempting self/cls parameters.',
 'Only enabled Java/Python checks and supported instruction files are analyzed. Vendor/build directories are excluded. This is not a compiler or security audit.',
]


def is_instruction(name):
    return name in {'AGENTS.md', 'CLAUDE.md', 'SKILL.md', 'copilot-instructions.md'} or name.endswith('.instructions.md')


def is_relevant(name, suffix, rules, catalog=RULES):
    languages = {catalog[rule]['language'] for rule in rules}
    return ((suffix == '.java' and 'Java' in languages)
            or (suffix == '.py' and 'Python' in languages)
            or is_instruction(name))


def compile_exclude(pattern):
    """Repository-relative glob: * and ? stay within one path segment, ** spans segments."""
    parts = pattern.split('/')
    regex = ''
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == '**':
            regex += '.*' if last else '(?:.*/)?'
        else:
            regex += ''.join('[^/]*' if c == '*' else '[^/]' if c == '?' else re.escape(c) for c in part)
            regex += '' if last else '/'
    return re.compile(regex)


def covered_symlink(root, path, rules, catalog=RULES):
    """A link to an analyzed regular file inside the repository loses nothing: the target is
    read at its own path. The link itself is never followed."""
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if not target.is_relative_to(root) or not target.is_file() or target.is_symlink():
        return False
    inside = target.relative_to(root)
    return not any(part in EXCLUDED for part in inside.parts[:-1]) and is_relevant(target.name, target.suffix, rules, catalog)


def fingerprint(rule, path, line_text):
    """Stable across line moves: rule + file + the finding's own line, whitespace-normalized.
    Editing that line produces a new fingerprint, so touched code must comply."""
    normalized = ' '.join(line_text.split())
    return hashlib.sha256(f'{rule}\0{path}\0{normalized}'.encode('utf-8')).hexdigest()[:32]


def with_fingerprints(findings, source):
    lines = re.split(r'\r\n|\r|\n', source)
    for finding in findings:
        text = lines[finding['line'] - 1] if 0 < finding['line'] <= len(lines) else ''
        finding['fingerprint'] = fingerprint(finding['rule'], finding['path'], text)
    return findings


def analyze(source, path, rules, catalog=RULES):
    if path.endswith('.java'):
        return java_checks.analyze(source, path, rules, catalog)
    if path.endswith('.py'):
        return python_checks.analyze(source, path, rules)
    return instructions.analyze(source, path, rules, catalog)


def scan(root, rules, exclude=(), catalog=RULES):
    findings, skipped = [], []
    count = 0
    analyzed = 0
    excluded = 0
    patterns = [compile_exclude(pattern) for pattern in exclude]
    def walk_error(error):
        raise error
    for directory, dirs, files in root.walk(on_error=walk_error, follow_symlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for name in sorted(files):
            path = directory / name
            rel = path.relative_to(root).as_posix()
            count += 1
            if count > 10_000:
                raise ValueError('Repository exceeds 10,000 file entries')
            if any(pattern.fullmatch(rel) for pattern in patterns):
                excluded += 1
                continue
            # Relevance first: a symlink the analysis would never read cannot make it incomplete.
            if not is_relevant(name, path.suffix, rules, catalog):
                continue
            if path.is_symlink():
                if not covered_symlink(root, path, rules, catalog):
                    skipped.append(dict(path=rel, reason='Symbolic link outside the analyzed files; not followed'))
                continue
            if not path.is_file() or path.stat().st_size > 1_000_000:
                skipped.append(dict(path=rel, reason='Not a regular file or exceeds 1 MB'))
                continue
            try:
                source = path.read_text(encoding='utf-8')
                findings.extend(with_fingerprints(analyze(source, rel, rules, catalog), source))
                analyzed += 1
            except UnicodeError:
                skipped.append(dict(path=rel, reason='Not UTF-8'))
            except SyntaxError as error:
                where = f' at line {error.lineno}' if error.lineno else ''
                skipped.append(dict(path=rel, reason=f'Python syntax error{where}: {error.msg}'))
            except java_checks.JavaSyntaxError as error:
                skipped.append(dict(path=rel, reason=str(error)))
    limitations = [*LIMITATIONS, *([f'{excluded} file(s) excluded by the approved policy scope: ' + ', '.join(exclude)] if excluded else [])]
    return dict(version=1, findings=sorted(findings, key=lambda f: (f['path'], f['line'], f['rule'])),
                skipped=skipped, limitations=limitations, analyzed_files=analyzed, approved_rules=len(rules),
                excluded_files=excluded)


def exit_code(report):
    if report['skipped'] or not report.get('approved_rules', 0):
        return 2
    # Baselined findings are known, accepted debt: they are reported but never block.
    return 1 if any(f['severity'] == 'error' and not f.get('baselined') for f in report['findings']) else 0
