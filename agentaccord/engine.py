"""Shared analysis engine for CLI and local app. Never runs repository code."""
import hashlib
import re
from . import java_checks, python_checks, instructions, json_checks
from .rules import RULES

EXCLUDED = {'.git', 'node_modules', 'target', 'build', 'dist', '.venv', 'venv', '__pycache__', '.idea'}
LIMITATIONS = [
 'Java resolves annotations from explicit imports, qualified names, and Java scoping rules; ambiguous wildcard/same-package names and import-free snippets are reported as incomplete. Custom meta-annotations and cross-file type resolution are unsupported.',
 'Instruction checks recognize direct affirmative patterns only. Java, Python, and JSON fenced examples are checked as non-blocking warnings, with labelled counter-examples omitted. Block quotes, indented code, and HTML comments are excluded; prose semantics and instruction precedence are not interpreted.',
 'Approved policies apply within their configured include/exclude paths. No inferred rule becomes blocking without approval.',
 'Python checks cover literal mutable defaults, missing function annotations, and bare except clauses. JSON checks syntax and duplicate object keys, not application schemas.',
 'Only enabled Java/Python/JSON checks and supported instruction files are analyzed. Vendor/build directories are excluded. This is not a compiler or security audit.',
]


def is_instruction(name):
    return name in {'AGENTS.md', 'CLAUDE.md', 'SKILL.md', 'copilot-instructions.md'} or name.endswith('.instructions.md')


def is_relevant(name, suffix, rules, catalog=RULES):
    languages = {catalog[rule]['language'] for rule in rules}
    return ((suffix == '.java' and 'Java' in languages)
            or (suffix == '.py' and 'Python' in languages)
            or (suffix == '.json' and 'JSON' in languages)
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
        finding['source_line'] = text[:500] + ('…' if len(text) > 500 else '')
        # JSON duplicate-key locations are document-level: include the whole document
        # so edits below line one cannot silently retain an accepted baseline.
        identity = source + '\0' + finding.get('evidence', '') if finding['rule'].startswith('json.') else text
        finding['fingerprint'] = fingerprint(finding['rule'], finding['path'], identity)
    return findings


def analyze(source, path, rules, catalog=RULES):
    if path.endswith('.java'):
        return java_checks.analyze(source, path, rules, catalog)
    if path.endswith('.json'):
        return json_checks.analyze(source, path, rules)
    if path.endswith('.py'):
        return python_checks.analyze(source, path, rules)
    return instructions.analyze(source, path, rules, catalog)


def scan(root, rules, exclude=(), catalog=RULES, examples=None, *, capture_scope=False):
    findings, skipped = [], []
    scope_files = []
    count = 0
    analyzed = 0
    excluded = 0
    example_files = 0
    counter_examples = []
    scoped_out = []
    example_patterns = [compile_exclude(p) for p in (examples.java if examples else ())]
    counter_patterns = [compile_exclude(p) for p in (examples.counter_examples if examples else ())]
    scopes = {rule: ([compile_exclude(p) for p in catalog[rule].get('include', ())],
                     [compile_exclude(p) for p in catalog[rule].get('exclude', ())]) for rule in rules}
    def applicable(rel):
        return {rule: severity for rule, severity in rules.items()
                if (not scopes[rule][0] or any(p.fullmatch(rel) for p in scopes[rule][0]))
                and not any(p.fullmatch(rel) for p in scopes[rule][1])}
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
                if capture_scope:
                    scope_files.append(dict(path=rel, status='excluded', rules=[], reason='Global exclusion'))
                continue
            # Relevance first: a symlink the analysis would never read cannot make it incomplete.
            if not is_relevant(name, path.suffix, rules, catalog):
                continue
            file_rules = applicable(rel)
            entry = dict(path=rel, status='skipped', rules=sorted(
                rule for rule in file_rules if is_relevant(name, path.suffix, {rule: file_rules[rule]}, catalog)))
            if capture_scope:
                scope_files.append(entry)
            omitted = sorted(set(rules) - set(file_rules))
            if omitted:
                scoped_out.append(dict(path=rel, rules=omitted))
            if rules and (not file_rules or not is_relevant(name, path.suffix, file_rules, catalog)):
                entry.update(status='out-of-scope', reason='No applicable approved rule')
                continue
            is_example = path.suffix == '.java' and any(p.fullmatch(rel) for p in example_patterns)
            if is_example and any(p.fullmatch(rel) for p in counter_patterns):
                entry.update(status='counter-example', reason='Explicit counter-example within Java example paths')
                counter_examples.append(rel)
                continue
            if path.is_symlink():
                try:
                    target = path.resolve(strict=True)
                except (OSError, RuntimeError):
                    skipped.append(dict(path=rel, reason='Unresolvable symbolic link; not followed'))
                    continue
                target_rel = target.relative_to(root).as_posix() if target.is_relative_to(root) else ''
                if (not covered_symlink(root, path, file_rules, catalog)
                        or any(p.fullmatch(target_rel) for p in patterns)
                        or set(file_rules) - set(applicable(target_rel))
                        or (any(p.fullmatch(target_rel) for p in example_patterns) and not is_example)
                        or (any(p.fullmatch(target_rel) for p in example_patterns)
                            and any(p.fullmatch(target_rel) for p in counter_patterns))):
                    skipped.append(dict(path=rel, reason='Symbolic link outside the analyzed files; not followed'))
                if not any(item['path'] == rel for item in skipped):
                    entry.update(status='covered-link', reason='Target checked at its own path')
                continue
            if not path.is_file() or path.stat().st_size > 1_000_000:
                skipped.append(dict(path=rel, reason='Not a regular file or exceeds 1 MB'))
                continue
            try:
                source = path.read_text(encoding='utf-8')
                if is_example:
                    matches = java_checks.analyze_snippet(source, file_rules, catalog, strict=True)
                    results = [dict(rule=rule, severity='warning', path=rel, line=line + 1,
                                    column=column, kind='example', confidence='example', evidence=evidence,
                                    message='Java example may conflict with approved policy: ' + catalog[rule]['title'],
                                    remediation=catalog[rule]['remediation'])
                               for rule, line, column, evidence in matches]
                    example_files += 1
                else:
                    results = analyze(source, rel, file_rules, catalog)
                for finding in results:
                    spec = catalog[finding['rule']]
                    finding['policy'] = dict(guidance=spec['guidance'],
                        include=spec.get('include', []), exclude=spec.get('exclude', []),
                        severity=file_rules[finding['rule']])
                findings.extend(with_fingerprints(results, source))
                entry['status'] = 'example' if is_example else 'analyzed'
                analyzed += 1
            except UnicodeError:
                skipped.append(dict(path=rel, reason='Not UTF-8'))
            except SyntaxError as error:
                where = f' at line {error.lineno}' if error.lineno else ''
                skipped.append(dict(path=rel, reason=f'Python syntax error{where}: {error.msg}'))
            except (java_checks.JavaSyntaxError, instructions.InstructionSyntaxError) as error:
                skipped.append(dict(path=rel, reason=str(error)))
            except (ValueError, RecursionError) as error:
                if path.suffix != '.json':
                    raise
                skipped.append(dict(path=rel, reason='Invalid or excessively nested JSON: ' + str(error)[:200]))
    limitations = [*LIMITATIONS, *([f'{excluded} file(s) excluded by the approved policy scope: ' + ', '.join(exclude)] if excluded else [])]
    if example_patterns:
        limitations.append(f'{example_files} Java example file(s) analyzed heuristically; findings are warnings, not proof of resolved annotation types. '
                           f'{len(counter_examples)} explicitly configured counter-example file(s) omitted.')
    if scoped_out:
        limitations.append(f'{len(scoped_out)} file(s) have rules omitted by per-rule path scopes; see rule_scope_omissions.')
    if capture_scope:
        reasons = {item['path']: item['reason'] for item in skipped}
        for entry in scope_files:
            if entry['path'] in reasons:
                entry['reason'] = reasons[entry['path']]
    return dict(version=1, findings=sorted(findings, key=lambda f: (f['path'], f['line'], f['rule'])),
                skipped=skipped, limitations=limitations, analyzed_files=analyzed, approved_rules=len(rules),
                excluded_files=excluded, example_files=example_files,
                counter_example_files=counter_examples, rule_scope_omissions=scoped_out,
                **({'scope_files': scope_files} if capture_scope else {}))


def exit_code(report):
    if report['skipped'] or report.get('comparison', {}).get('base_skipped') or not report.get('approved_rules', 0):
        return 2
    # Baselined findings are known, accepted debt: they are reported but never block.
    return 1 if any(f['severity'] == 'error' and not f.get('baselined') and f.get('change') != 'existing' for f in report['findings']) else 0
