"""Python rules use the standard-library AST, without importing scanned code."""
import ast
import re

RULES = {
 'python.no-bare-except': ('Bare except clause', 'Catch the specific exception types this operation can handle.'),
 'python.no-mutable-defaults': ('Mutable default argument', 'Use None as the default and create the collection inside the function.'),
 'python.require-type-hints': ('Missing function type annotation', 'Annotate parameters and the return type.'),
}


def analyze(source, path, rules):
    tree = ast.parse(source, filename=path)
    # Match the parser's line breaks; str.splitlines() also splits on form feeds and U+2028.
    lines = re.split(r'\r\n|\r|\n', source)
    findings = []
    def add(rule, node, message):
        severity = rules.get(rule, 'off')
        if severity == 'off':
            return
        # AST columns are UTF-8 byte offsets; report Unicode character columns.
        line = lines[node.lineno - 1]
        column = len(line.encode('utf-8')[:node.col_offset].decode('utf-8')) + 1
        findings.append(dict(rule=rule, severity=severity, path=path, line=node.lineno,
            column=column, kind='code', confidence='syntax', message=message,
            evidence=type(node).__name__, remediation=RULES[rule][1]))
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            add('python.no-bare-except', node, 'Bare except catches all exceptions, including process interruption')
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                add('python.no-mutable-defaults', default, 'Mutable collection literal used as a default argument')
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args += [a for a in (node.args.vararg, node.args.kwarg) if a]
        if node.returns is None or any(a.annotation is None and a.arg not in {'self', 'cls'} for a in args):
            add('python.require-type-hints', node, f'Function {node.name} is missing parameter or return annotations')
    return findings
