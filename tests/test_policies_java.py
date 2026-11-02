import tempfile
import unittest
from pathlib import Path
from agentaccord import configuration as config, instructions
from agentaccord.engine import analyze, scan
from agentaccord.java_checks import JavaSyntaxError

AUTOWIRED = 'org.springframework.beans.factory.annotation.Autowired'
RULES = {'spring.no-field-injection': 'error', 'spring.no-value': 'warning', 'spring.no-webmvctest': 'error'}

class JavaTests(unittest.TestCase):
    def test_field_injection_and_constructor_pass(self):
        source = f'import {AUTOWIRED}; class Service {{ @Autowired private Store store; @Autowired Service(Store store) {{ this.store = store; }} }}'
        result = analyze(source, 'Service.java', RULES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rule'], 'spring.no-field-injection')
        self.assertEqual(result[0]['confidence'], 'syntax')
        good = f'import {AUTOWIRED}; class Service {{ final Store store; @Autowired Service(Store store) {{ this.store = store; }} }}'
        self.assertEqual(analyze(good, 'Service.java', RULES), [])

    def test_jakarta_inject_and_resource(self):
        for annotation in ['jakarta.inject.Inject','javax.inject.Inject','jakarta.annotation.Resource','javax.annotation.Resource']:
            self.assertEqual(len(analyze(f'class A {{ @{annotation} Store store; }}', 'A.java', RULES)), 1)

    def test_setter_is_not_field_injection(self):
        self.assertEqual(analyze(f'class A {{ @{AUTOWIRED} void set(Store s) {{}} }}', 'A.java', RULES), [])

    def test_local_annotation_is_not_spring(self):
        self.assertEqual(analyze('@interface Value {} @Value class A {}', 'A.java', RULES), [])

    def test_parse_error_is_explicit(self):
        with self.assertRaises(JavaSyntaxError):
            analyze('class A {', 'A.java', RULES)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'A.java').write_text('class A {')
            self.assertEqual(len(scan(root, RULES)['skipped']), 1)

    def test_markdown_examples_not_directives(self):
        source = '\n'.join(['```java', 'Use @Value.', '```', '> Use @Value.', '    Use @Value.', '<!--', 'Use @Value.', '-->', '1. Use field injection.'])
        result = instructions.analyze(source, 'AGENTS.md', RULES)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['rule'], 'spring.no-field-injection')

    def test_wildcard_is_incomplete_not_clean(self):
        with self.assertRaises(JavaSyntaxError):
            analyze('import org.springframework.beans.factory.annotation.*; class A { @Autowired Store store; }', 'A.java', RULES)

    def test_unicode_column(self):
        source = 'class A { String café; @org.springframework.beans.factory.annotation.Value("x") String s; }'
        result = analyze(source,'A.java',RULES)
        self.assertEqual(result[0]['column'], source.index('@') + 1)

class PolicyTests(unittest.TestCase):
    def test_proposals_do_not_enforce(self):
        policy=config.Policy(rules={'spring.no-value':config.RulePolicy()})
        self.assertEqual(policy.active(), {})
        policy.rules['spring.no-value'].approved=True
        self.assertEqual(policy.active(), {'spring.no-value':'error'})

    def test_strict_yaml(self):
        invalid=['version: 2\nrules: {}', 'version: true\nrules: {}', 'version: 1\nextra: yes\nrules: {}', 'version: 1\nrules:\n  typo: {}', 'version: 1\nversion: 1\nrules: {}', 'version: 1\nrules: &rules {}', 'version: 1\nrules:\n  spring.no-value:\n    severity: fatal']
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for source in invalid:
                (root/'.agentaccord.yml').write_text(source)
                with self.subTest(source=source), self.assertRaises(ValueError):
                    config.load(root)

    def test_guidance_preserves_handwritten_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path=root/'AGENTS.md'
            original='# Team guidance\n\nKeep tests readable.\n'
            path.write_text(original)
            self.assertTrue(instructions.sync(root, {'spring.no-value':'error'}))
            first=path.read_text()
            self.assertTrue(first.startswith(original))
            self.assertFalse(instructions.sync(root, {'spring.no-value':'error'}))
            instructions.sync(root, {'spring.no-field-injection':'warning'})
            self.assertIn('Keep tests readable.', path.read_text())
            self.assertNotIn('spring.no-value',path.read_text())

    def test_guidance_malformed_markers_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root=Path(temp); path=root/'AGENTS.md'
            path.write_text(instructions.START)
            with self.assertRaises(ValueError): instructions.sync(root, {})
            path.unlink(); target=Path(other)/'AGENTS.md'; target.write_text('keep')
            path.symlink_to(target)
            with self.assertRaises(ValueError): instructions.sync(root, {})
            self.assertEqual(target.read_text(),'keep')

    def test_yaml_roundtrip_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'.agentcontract.toml').write_text('version=1\n[rules]\n"spring.no-value"="warning"')
            policy=config.load(root)
            self.assertEqual(policy.active(),{'spring.no-value':'warning'})
            config.save(root,policy)
            self.assertEqual(config.load(root),policy)
