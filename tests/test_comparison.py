import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentaccord.cli import main
from agentaccord.comparison import compare
from agentaccord.engine import exit_code
from agentaccord.github_action import main as action_main
from agentaccord.pr_reports import annotations, summary
from agentaccord.reporters import sarif

POLICY = 'version: 1\nrules:\n  spring.no-value:\n    approved: true\n'
SOURCE = 'import org.springframework.beans.factory.annotation.Value;\nclass A {\n @Value("x") String x;\n}\n'


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root/'base'; self.head = self.root/'head'
        self.base.mkdir(); self.head.mkdir()
        (self.base/'.agentaccord.yml').write_text(POLICY)

    def write_both(self, name, text):
        for root in (self.base, self.head):
            (root/name).write_text(text)

    def test_existing_findings_do_not_block_and_line_moves_match(self):
        self.write_both('A.java', SOURCE)
        (self.head/'A.java').write_text('\n\n'+SOURCE)
        report, _ = compare(self.head, self.base)
        self.assertEqual(exit_code(report), 0)
        self.assertEqual(report['findings'][0]['change'], 'existing')
        self.assertEqual(report['findings'][0]['line'], 5)
        self.assertEqual(annotations(report), '')
        self.assertIn('Existing findings', summary(report))
        self.assertEqual(sarif(report)['runs'][0]['results'][0]['baselineState'],'unchanged')

    def test_new_code_and_instruction_conflicts_grouped(self):
        self.write_both('A.java', SOURCE)
        (self.head/'AGENTS.md').write_text('Use @Value.\n')
        (self.head/'B.java').write_text(SOURCE.replace('class A', 'class B'))
        report, _ = compare(self.head, self.base)
        self.assertEqual(report['comparison']['new'],2)
        self.assertEqual(report['comparison']['existing'],1)
        self.assertEqual(exit_code(report),1)
        self.assertEqual(len(annotations(report).splitlines()),2)
        self.assertIn('New code conflicts (1)',summary(report))
        self.assertIn('New instruction conflicts (1)',summary(report))
        self.assertIn('Suggested fix:',summary(report))
        self.assertIn('file=AGENTS.md,line=1',annotations(report))

    def test_duplicate_occurrences_and_fixed_findings(self):
        self.write_both('A.java', SOURCE)
        (self.head/'A.java').write_text(SOURCE.replace(' @Value("x") String x;',' @Value("x") String x;\n @Value("x") String x;'))
        report, _ = compare(self.head,self.base)
        self.assertEqual(report['comparison']['new'],1)
        self.assertEqual(report['comparison']['existing'],1)
        (self.head/'A.java').write_text('class A {}')
        report,_=compare(self.head,self.base)
        self.assertEqual(report['comparison']['resolved'],1)
        self.assertEqual(exit_code(report),0)

    def test_head_cannot_disable_base_rules_or_accept_new_debt(self):
        (self.head/'.agentaccord.yml').write_text('version: 1\nrules: {}')
        (self.head/'.agentaccord-baseline.json').write_text('not even valid json')
        (self.head/'A.java').write_text(SOURCE)
        report,_=compare(self.head,self.base)
        self.assertEqual(exit_code(report),1)

    def test_base_or_head_parse_failure_remains_incomplete(self):
        for directory in (self.base,self.head):
            path=directory/'Broken.java';path.write_text('class A {')
            report,_=compare(self.head,self.base)
            self.assertEqual(exit_code(report),2)
            self.assertFalse(sarif(report)['runs'][0]['invocations'][0]['executionSuccessful'])
            path.unlink()

    def test_missing_policy_no_approval_and_overlapping_roots(self):
        (self.base/'.agentaccord.yml').unlink()
        with self.assertRaises(ValueError):compare(self.head,self.base)
        (self.base/'.agentaccord.yml').write_text('version: 1\nrules: {}')
        self.assertEqual(exit_code(compare(self.head,self.base)[0]),2)
        with self.assertRaises(ValueError):compare(self.base,self.base)
        with self.assertRaises(ValueError):compare(self.base,self.root)

    def test_cli_comparison_works_without_head_policy(self):
        (self.head/'A.java').write_text(SOURCE)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            status=main(['check',str(self.head),'--compare-to',str(self.base),'--format','json'])
        self.assertEqual(status,1)
        self.assertEqual(json.loads(output.getvalue())['comparison']['new'],1)

    def test_annotations_and_summary_escape_untrusted_content(self):
        (self.head/'A.java').write_text(SOURCE)
        report,_=compare(self.head,self.base)
        f=report['findings'][0]
        f.update(path='bad,\n::error::injected.java', message='<script>@everyone\n::error::owned',remediation='[click](https://example.com)')
        command=annotations(report)
        self.assertEqual(len(command.splitlines()),1)
        self.assertIn('%2C%0A',command)
        self.assertNotIn('<script>',summary(report))
        self.assertNotIn('@everyone',summary(report))
        self.assertIn('\\[click\\]',summary(report))

    def test_action_summary_outputs_and_nested_annotations(self):
        self.write_both('A.java',SOURCE)
        (self.head/'B.java').write_text(SOURCE)
        output=self.root/'outputs'; note=self.root/'summary'
        env={'TARGET':str(self.head),'BASE_TARGET':str(self.base),'GITHUB_WORKSPACE':str(self.root),
             'GITHUB_OUTPUT':str(output),'GITHUB_STEP_SUMMARY':str(note),'RUNNER_TEMP':str(self.root)}
        stdout=io.StringIO()
        with patch.dict(os.environ,env,clear=True),contextlib.redirect_stdout(stdout):
            self.assertEqual(action_main(),0)
        values=dict(line.split('=',1) for line in output.read_text().splitlines())
        self.assertEqual(values['exit-code'],'1')
        self.assertIn('file=head/B.java',stdout.getvalue())
        report=json.loads(Path(values['report-path']).read_text())
        self.assertEqual(report['comparison']['existing'],1)
        data=json.loads(Path(values['sarif-path']).read_text())
        self.assertTrue(all(r['locations'][0]['physicalLocation']['artifactLocation']['uri'].startswith('head/') for r in data['runs'][0]['results']))
        self.assertIn('Existing findings',note.read_text())

    def test_action_failure_emits_exit_two_without_injection(self):
        output=self.root/'outputs'; note=self.root/'summary'
        with patch.dict(os.environ,{'TARGET':str(self.root/'missing\n::error::fake'),
             'GITHUB_OUTPUT':str(output),'GITHUB_STEP_SUMMARY':str(note)},clear=True),contextlib.redirect_stdout(io.StringIO()) as stdout:
            action_main()
        self.assertEqual(output.read_text(),'exit-code=2\n')
        self.assertEqual(len(stdout.getvalue().splitlines()),1)
        self.assertIn('incomplete analysis',note.read_text())
