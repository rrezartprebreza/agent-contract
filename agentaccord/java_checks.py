"""Tree-sitter Java checks with conservative, file-local annotation resolution."""
import re
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


TEST_CLASS_ANNOTATIONS = {'SpringBootTest', 'WebMvcTest', 'WebFluxTest', 'DataJpaTest', 'DataJdbcTest', 'JdbcTest',
    'DataMongoTest', 'DataRedisTest', 'JsonTest', 'RestClientTest', 'GraphQlTest', 'ExtendWith', 'Nested'}
TEST_METHOD_ANNOTATIONS = {'Test', 'ParameterizedTest', 'RepeatedTest', 'TestFactory', 'TestTemplate'}


def annotation_names(modifiers, data):
    names = set()
    for child in (modifiers.named_children if modifiers else ()):
        if child.type in {'annotation', 'marker_annotation'}:
            name = child.child_by_field_name('name')
            if name:
                names.add(data[name.start_byte:name.end_byte].decode('utf-8').rsplit('.', 1)[-1])
    return names


def in_test_class(node, data):
    """Field injection is idiomatic in test classes (Spring's own test docs use it); teams that
    forbid it mean production components. Detected syntactically, never by file name."""
    current = node.parent
    while current is not None:
        if current.type == 'class_declaration':
            modifiers = next((c for c in current.named_children if c.type == 'modifiers'), None)
            if annotation_names(modifiers, data) & TEST_CLASS_ANNOTATIONS:
                return True
            body = current.child_by_field_name('body')
            for member in (body.named_children if body else ()):
                if member.type == 'method_declaration':
                    method_modifiers = next((c for c in member.named_children if c.type == 'modifiers'), None)
                    if annotation_names(method_modifiers, data) & TEST_METHOD_ANNOTATIONS:
                        return True
        current = current.parent
    return False


def on_field(node):
    parent = node.parent
    return bool(parent and parent.type == 'modifiers' and parent.parent and parent.parent.type == 'field_declaration')


def allowed_job_parameter(node, data, spec):
    """Only a whole literal lookup; arbitrary SpEL and property placeholders remain checked."""
    if not spec.get('allow_job_parameters'):
        return False
    arguments = node.child_by_field_name('arguments')
    if not arguments:
        return False
    value = data[arguments.start_byte:arguments.end_byte].decode('utf-8')
    return bool(re.fullmatch(
        r'''\(\s*(?:value\s*=\s*)?"#\{jobParameters\['[A-Za-z0-9_.-]+'\]\}"\s*\)''', value))


def remediation_for(rule, node, data, spec):
    """Use test-specific advice only for a literal port injection into a test field."""
    arguments = node.child_by_field_name('arguments')
    if rule == 'spring.no-value' and arguments and on_field(node) and in_test_class(node, data):
        value = data[arguments.start_byte:arguments.end_byte].decode('utf-8')
        if re.fullmatch(r'\(\s*(?:value\s*=\s*)?"\$\{local\.server\.port\}"\s*\)', value):
            return ('Use @LocalServerPort (org.springframework.boot.test.web.server.LocalServerPort) '
                    'to inject the running test server port, if this policy applies to your test.')
    return spec['remediation']


def analyze(source, path, policies, catalog=RULES):
    data = source.encode('utf-8')
    tree = Parser(JAVA).parse(data)
    root = tree.root_node
    if root.has_error:
        error = next((n for n in walk(root) if n.type == 'ERROR' or n.is_missing), root)
        raise JavaSyntaxError(f'Java syntax error near line {error.start_point.row + 1}')
    text = lambda n: data[n.start_byte:n.end_byte].decode('utf-8')
    imports = {}
    wildcards = set()
    package = None
    local_names = set()
    for node in walk(root):
        if node.type == 'package_declaration':
            name = next((c for c in node.named_children if c.type in ('scoped_identifier', 'identifier')), None)
            package = text(name) if name else None
        if node.type == 'import_declaration':
            imported = text(node).removeprefix('import').strip().removesuffix(';').strip()
            if imported.startswith('static '):
                continue
            if imported.endswith('.*'):
                wildcards.add(imported[:-2].strip())
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
            possible = {qualified.rsplit('.', 1)[0] for rule, severity in policies.items() if severity != 'off'
                        for qualified in catalog[rule].get('imports', []) if qualified.rsplit('.', 1)[-1] == name}
            if not possible:
                continue
            line = node.start_point.row + 1
            # In a compilation unit, an unimported simple name can only come from an on-demand
            # import or the file's own package. If neither could supply the policed annotation,
            # it is provably another type (e.g. lombok.Value via `import lombok.*`).
            if not (imports or wildcards or package):
                raise JavaSyntaxError(f'Cannot resolve @{name} at line {line}: no package or imports (code snippet?). '
                                      'Add the import, configure Java example paths, or exclude example files in the policy scope')
            if possible & (wildcards | {package}):
                raise JavaSyntaxError(f'Cannot resolve @{name} at line {line}; a wildcard or same-package type may supply it. '
                                      'Use an explicit import for supported analysis')
            continue
        for rule, severity in policies.items():
            spec = catalog[rule]
            if severity == 'off' or resolved not in spec.get('imports', []):
                continue
            if allowed_job_parameter(node, data, spec):
                continue
            if spec.get('target') == 'field' and not on_field(node):
                continue
            if spec.get('skip_test_classes') and in_test_class(node, data):
                continue
            prefix = data[:node.start_byte].decode('utf-8')
            findings.append(dict(rule=rule, severity=severity, path=path,
                line=node.start_point.row + 1, column=len(prefix.rsplit('\n', 1)[-1]) + 1,
                kind='code', confidence='syntax', evidence='@' + name,
                message=spec.get('message') or f'@{name.rsplit(".", 1)[-1]} is prohibited by approved policy',
                remediation=remediation_for(rule, node, data, spec)))
    return findings


# Class body first: the Java grammar also accepts top-level statements, so a bare
# `@Autowired private Store store;` would otherwise parse as a local variable, not a field.
SNIPPET_WRAPPERS = (('class Snippet {\n', '\n}'), ('', ''), ('class Snippet { void snippet() {\n', '\n} }'))


def analyze_snippet(source, policies, catalog=RULES, *, strict=False):
    """Annotation uses in a documentation code example, as (rule, line, column, evidence).

    Examples may omit imports, so unresolved names match heuristically by their simple name.
    Explicit imports, qualified names and locally declared types take precedence. Annotations that need an
    argument in the policed library (Spring's @Value) only match with one, which keeps
    argument-less look-alikes such as Lombok's @Value out. Non-Java text yields nothing."""
    for prefix, suffix in SNIPPET_WRAPPERS:
        data = (prefix + source + suffix).encode('utf-8')
        root = Parser(JAVA).parse(data).root_node
        if not root.has_error:
            break
    else:
        if strict:
            raise JavaSyntaxError('Java example could not be parsed, including supported snippet wrappers')
        return []
    offset = prefix.count('\n')
    imports, local_names = {}, set()
    for node in walk(root):
        text = data[node.start_byte:node.end_byte].decode('utf-8')
        if node.type == 'import_declaration':
            qualified = text.removeprefix('import').strip().removesuffix(';').strip()
            if not qualified.startswith('static ') and not qualified.endswith('.*'):
                imports[qualified.rsplit('.', 1)[-1]] = qualified
        if node.type in {'class_declaration', 'interface_declaration', 'annotation_type_declaration',
                         'enum_declaration', 'record_declaration'}:
            name_node = node.child_by_field_name('name')
            if name_node:
                local_names.add(data[name_node.start_byte:name_node.end_byte].decode('utf-8'))
    wanted = {}
    for rule, severity in policies.items():
        if severity == 'off':
            continue
        for qualified in catalog[rule].get('imports', []):
            wanted.setdefault(qualified.rsplit('.', 1)[-1], set()).add(rule)
    matches = []
    for node in walk(root):
        if node.type not in {'annotation', 'marker_annotation'}:
            continue
        name_node = node.child_by_field_name('name')
        if not name_node:
            continue
        name = data[name_node.start_byte:name_node.end_byte].decode('utf-8')
        if '.' not in name and name in local_names:
            continue
        resolved = name if '.' in name else imports.get(name)
        for rule in sorted(wanted.get(name.rsplit('.', 1)[-1], ())):
            spec = catalog[rule]
            if resolved and resolved not in spec.get('imports', []):
                continue
            if allowed_job_parameter(node, data, spec):
                continue
            if spec.get('target') == 'field' and not on_field(node):
                continue
            if spec.get('skip_test_classes') and in_test_class(node, data):
                continue
            if spec.get('snippet_requires_arguments') and node.type != 'annotation':
                continue
            line = node.start_point.row - offset
            prefix_bytes = data[:node.start_byte].decode('utf-8').rsplit('\n', 1)[-1]
            matches.append((rule, line, len(prefix_bytes) + 1, '@' + name))
    return matches
