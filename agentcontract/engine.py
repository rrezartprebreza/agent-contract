"""Shared analysis engine for CLI and local app. Never runs repository code."""
from . import java_checks, python_checks, instructions

EXCLUDED = {'.git', 'node_modules', 'target', 'build', 'dist', '.venv', 'venv', '__pycache__', '.idea'}
LIMITATIONS = [
 'Java requires an explicit import or fully qualified Spring/Jakarta/Javax annotation. Custom meta-annotations and cross-file type resolution are unsupported.',
 'Instruction checks recognize direct affirmative patterns only. Fenced examples, block quotes, indented code, and HTML comments are excluded; prose semantics and instruction precedence are not interpreted.',
 'Approved policies apply to the entire selected repository. No inferred rule becomes blocking without approval.',
 'Python checks cover literal list/dict/set defaults and missing function annotations, exempting self/cls parameters.',
 'Only enabled Java/Python checks and supported instruction files are analyzed. Vendor/build directories are excluded. This is not a compiler or security audit.',
]


def is_instruction(name):
    return name in {'AGENTS.md', 'CLAUDE.md', 'SKILL.md', 'copilot-instructions.md'} or name.endswith('.instructions.md')


def analyze(source, path, rules):
    if path.endswith('.java'):
        return java_checks.analyze(source, path, rules)
    if path.endswith('.py'):
        return python_checks.analyze(source, path, rules)
    return instructions.analyze(source, path, rules)


def scan(root, rules):
    findings, skipped = [], []
    count = 0
    analyzed = 0
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
            if path.is_symlink():
                skipped.append(dict(path=rel, reason='Symbolic link; not followed'))
                continue
            relevant = (path.suffix == '.java' and any(k.startswith('spring.') for k in rules)) or (path.suffix == '.py' and any(k.startswith('python.') for k in rules)) or is_instruction(name)
            if not relevant:
                continue
            if not path.is_file() or path.stat().st_size > 1_000_000:
                skipped.append(dict(path=rel, reason='Not a regular file or exceeds 1 MB'))
                continue
            try:
                source = path.read_text(encoding='utf-8')
                findings.extend(analyze(source, rel, rules))
                analyzed += 1
            except UnicodeError:
                skipped.append(dict(path=rel, reason='Not UTF-8'))
            except SyntaxError as error:
                skipped.append(dict(path=rel, reason=f'Python syntax error at line {error.lineno}'))
            except java_checks.JavaSyntaxError as error:
                skipped.append(dict(path=rel, reason=str(error)))
    return dict(version=1, findings=sorted(findings, key=lambda f: (f['path'], f['line'], f['rule'])),
                skipped=skipped, limitations=LIMITATIONS, analyzed_files=analyzed, approved_rules=len(rules))


def exit_code(report):
    if report['skipped'] or not report.get('approved_rules', 0):
        return 2
    return 1 if any(f['severity'] == 'error' for f in report['findings']) else 0
