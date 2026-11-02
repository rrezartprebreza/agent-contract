import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from agentaccord.cli import CONFIG, analyze, main, scan
from agentaccord.configuration import Policy, RulePolicy, save

RULES = {'spring.no-webmvctest': 'error', 'spring.no-value': 'warning'}
WEB = 'org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest'
VALUE = 'org.springframework.beans.factory.annotation.Value'

class ContractTests(unittest.TestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = main(args)
        return status, output.getvalue()

    def test_annotations_and_locations(self):
        result = analyze(f'import {WEB};\n@WebMvcTest\nclass Test {{}}', 'Test.java', RULES)
        self.assertEqual([(f['line'], f['column']) for f in result], [(2, 1)])

    def test_comments_strings_and_unrelated_annotation(self):
        source = f'import {VALUE};\n// @WebMvcTest\n/* @Value */\nclass Test {{ String s = "@WebMvcTest"; String t = """\n@Value\n"""; }}'
        self.assertEqual(analyze(source, 'Test.java', RULES), [])
        self.assertEqual(analyze('import example.Value; @Value class Test {}', 'Test.java', RULES), [])

    def test_qualified_annotation(self):
        self.assertEqual(len(analyze(f'@{VALUE}("x") class Test {{}}', 'Test.java', RULES)), 1)

    def test_instruction_conflict(self):
        result = analyze('Use @WebMvcTest for controller tests.', 'AGENTS.md', RULES)
        self.assertEqual(result[0]['kind'], 'instruction')

    def test_negative_and_conditional_guidance(self):
        self.assertEqual(analyze('Do not use @WebMvcTest.\nUse @WebMvcTest if approved.', 'AGENTS.md', RULES), [])

    def test_off_rule(self):
        self.assertEqual(analyze(f'@{VALUE}("x") class Test {{}}', 'A.java', {'spring.no-value': 'off'}), [])

    def test_demo_end_to_end(self):
        root = Path(__file__).resolve().parents[1]
        status, output = self.invoke('check', str(root / 'examples/conflicting'), '--format', 'json')
        self.assertEqual(status, 1)
        self.assertEqual(len(json.loads(output)['findings']), 3)
        self.assertEqual(self.invoke('check', str(root / 'examples/passing'))[0], 0)

    def test_init_requires_approval_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.invoke('init', temp)[0], 0)
            self.assertEqual(self.invoke('init', temp)[0], 2)
            self.assertEqual(self.invoke('check', temp)[0], 2)
            save(Path(temp), Policy(rules={key: RulePolicy(approved=True) for key in RULES}))
            status, output = self.invoke('guidance', temp)
            self.assertEqual(status, 0)
            self.assertEqual(analyze(output, 'AGENTS.md', RULES), [])

    def test_invalid_legacy_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / '.agentcontract.toml'
            for config in ['version=2', 'version=1\n[rules]\nunknown="error"', 'version=1\n[rules]\n"spring.no-value"="oops"']:
                p.write_text(config)
                self.assertEqual(self.invoke('check', temp)[0], 2)

    def test_symlink_and_excluded_directory(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            external = Path(outside) / 'Secret.java'
            external.write_text(f'@{WEB} class Test {{}}')
            (root / 'Link.java').symlink_to(external)
            (root / 'target').mkdir()
            (root / 'target' / 'Ignored.java').write_text('@WebMvcTest')
            result = scan(root, RULES)
            self.assertEqual(result['findings'], [])
            self.assertEqual(len(result['skipped']), 1)
            (root / '.agentcontract.toml').write_text(CONFIG)
            self.assertEqual(self.invoke('check', temp)[0], 2)

    def test_warning_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.agentcontract.toml').write_text(CONFIG)
            (root / 'Settings.java').write_text(f'class Settings {{ @{VALUE}("x") String value; }}')
            self.assertEqual(self.invoke('check', temp)[0], 0)
