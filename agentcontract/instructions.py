"""Deliberately narrow conflict patterns and a protected generated guidance block."""
import re
from .rules import RULES
from .configuration import read_regular

START = '<!-- agentcontract:begin -->'
END = '<!-- agentcontract:end -->'


def guidance(policies):
    lines = [START, '## Approved engineering policies', '', 'Generated from the approved AgentContract policy.']
    lines += [f'- {RULES[rule]["guidance"]} [{rule}; {severity}]' for rule, severity in sorted(policies.items()) if severity != 'off']
    return '\n'.join([*lines, END, ''])


def sync(root, policies):
    path = root / 'AGENTS.md'
    original = read_regular(path) if path.exists() or path.is_symlink() else ''
    if original.count(START) != original.count(END) or original.count(START) > 1:
        raise ValueError('Malformed AgentContract guidance markers; refusing to modify AGENTS.md')
    block = guidance(policies)
    if START in original:
        start, end = original.index(START), original.index(END)
        if end < start:
            raise ValueError('Guidance end marker precedes start marker')
        result = original[:start] + block.rstrip('\n') + original[end + len(END):]
    else:
        result = original.rstrip('\n') + ('\n\n' if original else '') + block
    if result == original:
        return False
    # Only the generated section is replaced; handwritten sections are retained.
    from .configuration import atomic_write
    atomic_write(path, result)
    return True


def analyze(source, path, policies):
    findings = []
    fence = None
    in_comment = False
    for number, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        marker = re.match(r'^(`{3,}|~{3,})', stripped)
        if marker:
            value = marker[1]
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence or line.startswith(('    ', '\t')) or stripped.startswith('>'):
            continue
        if '<!--' in line:
            in_comment = True
        if in_comment:
            if '-->' in line:
                in_comment = False
            continue
        sentence = re.sub(r'^\s*(?:[-*]|\d+[.)])\s+', '', line).strip()
        if re.search(r"\b(if|unless|except|not|never|avoid|don't)\b", sentence, re.I):
            continue
        for rule, severity in policies.items():
            if severity == 'off':
                continue
            if rule == 'spring.no-field-injection':
                pattern = r'^(?:use|prefer|always use)\s+field injection\b'
            elif rule in {'spring.no-webmvctest', 'spring.no-value'}:
                pattern = r'^(?:use|prefer|always use)\s+`?@' + RULES[rule]['annotation'] + r'\b'
            else:
                continue
            if re.search(pattern, sentence, re.I):
                findings.append(dict(rule=rule, severity=severity, path=path, line=number,
                    column=len(line) - len(line.lstrip()) + 1, kind='instruction', confidence='pattern',
                    message='Instruction contradicts an approved policy: ' + RULES[rule]['title'],
                    evidence=sentence[:240], remediation=RULES[rule]['guidance']))
    return findings
