"""Tree-sitter Java checks with conservative, file-local annotation resolution."""
from tree_sitter import Language, Parser
import tree_sitter_java
from .rules import RULES

JAVA = Language(tree_sitter_java.language())

class JavaSyntaxError(ValueError):
    pass


def walk(node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(reversed(item.named_children))


def analyze(source, path, policies):
    data = source.encode('utf-8')
    tree = Parser(JAVA).parse(data)
    root = tree.root_node
    if root.has_error:
        error = next((n for n in walk(root) if n.type == 'ERROR' or n.is_missing), root)
        raise JavaSyntaxError(f'Java syntax error near line {error.start_point.row + 1}')
    text = lambda n: data[n.start_byte:n.end_byte].decode('utf-8')
    imports = {}
    local_names = set()
    for node in walk(root):
        if node.type == 'import_declaration':
            imported = text(node).removeprefix('import').strip().removesuffix(';').strip()
            if imported.startswith('static '):
                continue
            if imported.endswith('.*'):
                pass
            else:
                imports[imported.rsplit('.', 1)[-1]] = imported
        if node.type in {'class_declaration', 'interface_declaration', 'annotation_type_declaration', 'enum_declaration', 'record_declaration'}:
            name = node.child_by_field_name('name')
            if name:
                local_names.add(text(name))
    findings = []
    for node in walk(root):
        if node.type not in {'annotation', 'marker_annotation'}:
            continue
        name_node = node.child_by_field_name('name')
        if not name_node:
            continue
        name = text(name_node)
        resolved = name if '.' in name else imports.get(name)
        # A single wildcard import is still not proof: a same-package type may shadow it.
        if '.' not in name and name in local_names:
            continue
        if not resolved:
            candidates = {qualified.rsplit('.', 1)[-1] for rule, severity in policies.items() if severity != 'off' for qualified in RULES[rule].get('imports', [])}
            if name in candidates:
                raise JavaSyntaxError(f'Cannot resolve @{name} at line {node.start_point.row + 1}; use an explicit import for supported analysis')
            continue
        for rule, severity in policies.items():
            spec = RULES[rule]
            if severity == 'off' or resolved not in spec.get('imports', []):
                continue
            if rule == 'spring.no-field-injection':
                parent = node.parent
                if not parent or parent.type != 'modifiers' or not parent.parent or parent.parent.type != 'field_declaration':
                    continue
            prefix = data[:node.start_byte].decode('utf-8')
            findings.append(dict(rule=rule, severity=severity, path=path,
                line=node.start_point.row + 1, column=len(prefix.rsplit('\n', 1)[-1]) + 1,
                kind='code', confidence='syntax', evidence='@' + name,
                message='Field injection violates the approved constructor-injection policy' if rule == 'spring.no-field-injection' else f'@{name.rsplit(".", 1)[-1]} is prohibited by approved policy',
                remediation=spec['remediation']))
    return findings
