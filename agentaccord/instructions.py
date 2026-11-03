"""Deliberately narrow conflict patterns and a protected generated guidance block."""
import re
from .rules import RULES
from .java_checks import analyze_snippet
from . import python_checks, json_checks

class InstructionSyntaxError(ValueError):
    pass

from .configuration import read_regular

START = '<!-- agentaccord:begin -->'
END = '<!-- agentaccord:end -->'
# Markers written by AgentContract (the project's former name); migrated on the next sync.
LEGACY_START = '<!-- agentcontract:begin -->'
LEGACY_END = '<!-- agentcontract:end -->'


def guidance(policies, catalog=RULES):
    lines = [START, '## Approved engineering policies', '', 'Generated from the approved AgentAccord policy.']
    lines += [f'- {catalog[rule]["guidance"]} [{rule}; {severity}]' for rule, severity in sorted(policies.items()) if severity != 'off']
    return '\n'.join([*lines, END, ''])


def sync(root, policies, catalog=RULES):
    path = root / 'AGENTS.md'
    original = read_regular(path) if path.exists() or path.is_symlink() else ''
    current = original.count(START) + original.count(END)
    legacy = original.count(LEGACY_START) + original.count(LEGACY_END)
    if current and legacy:
        raise ValueError('AGENTS.md contains both AgentAccord and legacy AgentContract markers; keep one block')
    start_marker, end_marker = (LEGACY_START, LEGACY_END) if legacy else (START, END)
    if original.count(start_marker) != original.count(end_marker) or original.count(start_marker) > 1:
        raise ValueError('Malformed AgentAccord guidance markers; refusing to modify AGENTS.md')
    block = guidance(policies, catalog)
    if start_marker in original:
        start, end = original.index(start_marker), original.index(end_marker)
        if end < start:
            raise ValueError('Guidance end marker precedes start marker')
        result = original[:start] + block.rstrip('\n') + original[end + len(end_marker):]
    else:
        result = original.rstrip('\n') + ('\n\n' if original else '') + block
    if result == original:
        return False
    # Only the generated section is replaced; handwritten sections are retained.
    from .configuration import atomic_write
    atomic_write(path, result)
    return True


# A labelled counter-example is teaching material, not guidance. ✅/Good wins over ❌/Bad.
NEGATIVE = re.compile(r"❌|✗|⛔|\b(?:bad|wrong|incorrect|avoid|anti-?pattern|don'?t|do not|never|before|without)\b", re.I)
POSITIVE = re.compile(r'✅|✔|\b(?:good|correct|recommended|preferred|after)\b', re.I)
EXAMPLE_LANGUAGES = {'', 'java', 'python', 'py', 'json'}


def counter_example(block_lines, context):
    for text in [*[line for line in block_lines if line.strip()][:3], *reversed(context)]:
        if POSITIVE.search(text):
            return False
        if NEGATIVE.search(text):
            return True
    return False


def directive_pattern(rule, spec):
    phrase = spec.get('instruction_phrase')
    if phrase:
        return r'^(?:use|prefer|always use)\s+' + re.escape(phrase) + r'\b'
    if spec.get('annotation'):
        return r'^(?:use|prefer|always use)\s+`?@' + re.escape(spec['annotation']) + r'\b'
    return None


def analyze(source, path, policies, catalog=RULES):
    findings = []
    fence = None
    block, block_start, block_language, block_context = [], 0, '', []
    context = []  # the two most recent prose lines, for counter-example labels
    in_comment = False
    in_list = False
    lines = source.splitlines()
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        marker = re.match(r'^(`{3,}|~{3,})', stripped)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
                info = stripped[len(value):].strip()
                block, block_start, block_context = [], number + 1, list(context)
                block_language = info.split()[0].lower() if info else ''
            elif value[0] == fence[0] and len(value) >= len(fence) and not stripped[len(value):].strip():
                fence = None
                findings.extend(example_findings(block, block_start, block_language, block_context, path, policies, catalog))
            continue
        if fence:
            block.append(line)
            continue
        if not stripped:
            continue
        context = [*context, stripped][-2:]
        indented = line.startswith(('    ', '\t'))
        is_item = re.match(r'^(?:[-*+]|\d+[.)])\s+', stripped) is not None
        # Indented text inside a list is list content (nested items, continuations), not code.
        if indented and not (in_list or is_item):
            continue
        if not indented:
            in_list = is_item
        if stripped.startswith('>'):
            continue
        if '<!--' in line:
            in_comment = True
        if in_comment:
            if '-->' in line:
                in_comment = False
            continue
        sentence = re.sub(r'^\s*(?:[-*+]|\d+[.)])\s+', '', line).strip()
        if re.search(r"\b(if|unless|except|not|never|avoid|don't)\b", sentence, re.I):
            continue
        for rule, severity in policies.items():
            pattern = directive_pattern(rule, catalog[rule]) if severity != 'off' else None
            if pattern and re.search(pattern, sentence, re.I):
                findings.append(dict(rule=rule, severity=severity, path=path, line=number,
                    column=len(line) - len(line.lstrip()) + 1, kind='instruction', confidence='pattern',
                    message='Instruction contradicts an approved policy: ' + catalog[rule]['title'],
                    evidence=sentence[:240], remediation=catalog[rule]['guidance']))
    return findings


def example_findings(block, start, language, context, path, policies, catalog):
    """Code examples teach agents as strongly as prose. Reported as warnings: they are
    heuristic and must never block a build on their own."""
    if language not in EXAMPLE_LANGUAGES or counter_example(block, context):
        return []
    findings = []
    if language in {'python', 'py', 'json'}:
        target_language = 'JSON' if language == 'json' else 'Python'
        active = {rule: severity for rule, severity in policies.items() if catalog[rule]['language'] == target_language}
        if not active:
            return []
        analyzer = json_checks.analyze if language == 'json' else python_checks.analyze
        try:
            matches = analyzer('\n'.join(block), path, active)
        except (ValueError, SyntaxError, RecursionError) as error:
            raise InstructionSyntaxError(f'{target_language} example starting at line {start} could not be parsed: {str(error)[:160]}') from error
        for match in matches:
            match.update(line=start + match['line'] - 1, severity='warning', kind='instruction', confidence='example')
            if language == 'json':
                match['message'] = match['message'].replace('document-level location', 'code-block start location')
                match['remediation'] = match['remediation'].replace('document start', 'code-block start')
            match['message'] = 'Code example: ' + match['message']
        return matches
    for rule, index, column, evidence in analyze_snippet('\n'.join(block), policies, catalog):
        findings.append(dict(rule=rule, severity='warning', path=path, line=start + index,
            column=column, kind='instruction', confidence='example',
            message='Code example teaches a pattern the approved policy prohibits: ' + catalog[rule]['title'],
            evidence=evidence, remediation=catalog[rule]['guidance'] + ' Label intentional counter-examples with ❌ or "Bad".'))
    return findings
