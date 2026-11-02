"""AgentAccord was called AgentContract: repositories using the old file names keep working."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from agentaccord import baseline, configuration as config, instructions
from agentaccord.cli import main
from agentaccord.engine import scan

AUTOWIRED = 'org.springframework.beans.factory.annotation.Autowired'
RULE = {'spring.no-field-injection': 'error'}
LEGACY_POLICY = 'version: 1\nrules:\n  spring.no-field-injection: {enabled: true, approved: true, severity: error}\n'


class RenameCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            return main([args[0], str(self.root), *args[1:]]), output.getvalue()

    def test_legacy_yaml_policy_is_read_and_new_file_takes_precedence(self):
        (self.root / '.agentcontract.yml').write_text(LEGACY_POLICY)
        self.assertEqual(config.load(self.root).active(), RULE)
        config.save(self.root, config.Policy(rules={'spring.no-value': config.RulePolicy(approved=True)}))
        self.assertTrue((self.root / '.agentaccord.yml').is_file())
        self.assertTrue((self.root / '.agentcontract.yml').is_file())  # retained, not deleted
        self.assertEqual(config.load(self.root).active(), {'spring.no-value': 'error'})

    def test_init_refuses_when_a_legacy_policy_exists(self):
        (self.root / '.agentcontract.yml').write_text(LEGACY_POLICY)
        status, output = self.run_cli('init')
        self.assertEqual(status, 2)
        self.assertIn('refusing overwrite', output)
        self.assertFalse((self.root / '.agentaccord.yml').exists())

    def test_legacy_guidance_markers_are_migrated_in_place(self):
        agents = self.root / 'AGENTS.md'
        agents.write_text('# Handwritten\nKeep me.\n\n<!-- agentcontract:begin -->\nold block\n<!-- agentcontract:end -->\n\nTail.\n')
        self.assertTrue(instructions.sync(self.root, RULE))
        text = agents.read_text()
        self.assertNotIn('agentcontract:', text)
        self.assertEqual((text.count(instructions.START), text.count(instructions.END)), (1, 1))
        self.assertIn('Keep me.', text)
        self.assertTrue(text.rstrip().endswith('Tail.'))
        self.assertFalse(instructions.sync(self.root, RULE))  # idempotent after migration

    def test_mixed_old_and_new_markers_are_refused(self):
        original = (f'{instructions.LEGACY_START}\na\n{instructions.LEGACY_END}\n'
                    f'{instructions.START}\nb\n{instructions.END}\n')
        (self.root / 'AGENTS.md').write_text(original)
        with self.assertRaisesRegex(ValueError, 'both AgentAccord and legacy'):
            instructions.sync(self.root, RULE)
        self.assertEqual((self.root / 'AGENTS.md').read_text(), original)

    def test_legacy_baseline_is_honored_and_never_overwritten(self):
        (self.root / '.agentcontract.yml').write_text(LEGACY_POLICY)
        (self.root / 'A.java').write_text(f'package a;\nimport {AUTOWIRED};\nclass A {{ @Autowired Store s; }}\n')
        self.assertEqual(self.run_cli('baseline')[0], 0)
        legacy = self.root / '.agentcontract-baseline.json'
        (self.root / '.agentaccord-baseline.json').rename(legacy)  # as written by the old tool
        self.assertEqual(self.run_cli('check')[0], 0)
        status, output = self.run_cli('baseline')
        self.assertEqual(status, 2)
        self.assertIn('.agentcontract-baseline.json already exists', output)
        report = baseline.apply(scan(self.root, RULE), self.root)
        self.assertEqual(report['baseline']['accepted'], 1)
        self.assertEqual(json.loads(legacy.read_text())['version'], 1)


if __name__ == '__main__':
    unittest.main()
