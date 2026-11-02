import json
import tempfile
import unittest
from pathlib import Path
from agentcontract.cli import analyze, scan, main
from agentcontract.reporters import dashboard, sarif
from agentcontract.discovery import discover
import test_cli

class ReportTests(unittest.TestCase):
    invoke = test_cli.ContractTests.invoke
    def test_python_ast(self):
        rules = {'python.no-mutable-defaults': 'error', 'python.require-type-hints': 'warning'}
        bad = analyze('def load(items=[]):\n    return items\n', 'app.py', rules)
        self.assertEqual({f['rule'] for f in bad}, set(rules))
        self.assertTrue(all(f['confidence'] == 'syntax' for f in bad))
        self.assertEqual(analyze('def load(items: list | None = None) -> list:\n    return []\n', 'app.py', rules), [])

    def test_python_syntax_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'app.py').write_text('def broken(')
            result = scan(root, {'python.no-mutable-defaults': 'error'})
            self.assertEqual(len(result['skipped']), 1)

    def test_html_escapes_untrusted_paths(self):
        result = {'findings': analyze('@org.springframework.beans.factory.annotation.Value("x") class Test {}', '<script>alert(1)</script>.java', {'spring.no-value': 'warning'}), 'skipped': [], 'limitations': []}
        output = dashboard(result)
        self.assertNotIn('<script>alert(1)</script>', output)
        self.assertIn('&lt;script&gt;', output)
        self.assertNotIn('https://', output)

    def test_sarif_structure(self):
        report = {'findings': analyze('@org.springframework.beans.factory.annotation.Value("x") class Test {}', 'a #.java', {'spring.no-value': 'warning'}), 'skipped': [], 'limitations': []}
        result = sarif(report)
        self.assertEqual(result['version'], '2.1.0')
        finding = result['runs'][0]['results'][0]
        self.assertEqual(finding['level'], 'warning')
        location = finding['locations'][0]['physicalLocation']
        self.assertEqual(location['artifactLocation']['uri'], 'a%20%23.java')
        self.assertEqual(location['region']['startLine'], 1)

    def test_report_output_no_overwrite(self):
        root = Path(__file__).resolve().parents[1] / 'examples/conflicting'
        with tempfile.TemporaryDirectory() as temp:
            output = str(Path(temp) / 'report.html')
            self.assertEqual(self.invoke('check', str(root), '--format', 'html', '--output', output)[0], 1)
            self.assertTrue(Path(output).read_text().startswith('<!doctype html>'))
            self.assertEqual(self.invoke('check', str(root), '--format', 'html', '--output', output)[0], 2)

    def test_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'pom.xml').write_text('<project/>')
            (root / 'Test.java').write_text('class Test {}')
            (root / 'AGENTS.md').write_text('rules')
            result = discover(root)
            self.assertEqual(result['languages'], {'Java': 1})
            self.assertEqual(result['manifests'][0]['technology'], 'Maven')
            self.assertEqual(result['instructions'], ['AGENTS.md'])

    def test_doctor_and_rules(self):
        root = Path(__file__).resolve().parents[1] / 'examples/passing'
        self.assertEqual(self.invoke('doctor', str(root))[0], 0)
        self.assertIn('python.no-mutable-defaults', self.invoke('rules', str(root))[1])
