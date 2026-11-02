"""Baselines accept existing findings so a team can adopt checks without fixing everything first."""
import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from agentaccord import baseline, configuration as config
from agentaccord.cli import main
from agentaccord.engine import exit_code, scan
from agentaccord.reporters import dashboard, sarif
from agentaccord.server import make_server

AUTOWIRED = 'org.springframework.beans.factory.annotation.Autowired'
VALUE = 'org.springframework.beans.factory.annotation.Value'


def service(*fields, prefix=''):
    body = '\n'.join(f'    @Autowired Store {name};' for name in fields)
    return f'package a;\nimport {AUTOWIRED};\n{prefix}class Service {{\n{body}\n}}\n'


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        config.save(self.root, config.Policy(rules={'spring.no-field-injection': config.RulePolicy(approved=True)}))

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = main([*args[:1], str(self.root), *args[1:]])
        return status, output.getvalue()

    def check(self):
        policy = config.load(self.root)
        return baseline.apply(scan(self.root, policy.active(), policy.exclude, policy.catalog()), self.root)

    def test_existing_findings_stop_blocking_new_ones_still_fail(self):
        self.write('Service.java', service('store'))
        self.assertEqual(self.run_cli('check')[0], 1)
        status, output = self.run_cli('baseline')
        self.assertEqual(status, 0)
        self.assertIn('accepting 1 existing finding', output)
        status, output = self.run_cli('check')
        self.assertEqual(status, 0)
        self.assertIn('0 finding(s) · 1 accepted by baseline', output)
        self.write('Other.java', service('cache').replace('Service', 'Other'))
        status, output = self.run_cli('check')
        self.assertEqual(status, 1)
        self.assertIn('Other.java', output)
        self.assertNotIn('Service.java', output)

    def test_moved_lines_stay_baselined_edited_lines_become_new(self):
        self.write('Service.java', service('store'))
        self.run_cli('baseline')
        self.write('Service.java', service('store', prefix='// a new comment\n\n\n'))
        self.assertEqual(exit_code(self.check()), 0)
        self.write('Service.java', service('repository'))
        self.assertEqual(exit_code(self.check()), 1)

    def test_counts_matter_for_identical_lines(self):
        self.write('Service.java', service('store', 'cache'))
        self.run_cli('baseline')
        self.write('Service.java', service('store', 'cache', 'store'))  # a second identical line
        report = self.check()
        self.assertEqual([f['baselined'] for f in report['findings']].count(False), 1)
        self.assertEqual(exit_code(report), 1)

    def test_never_overwrites_and_prune_only_shrinks(self):
        self.write('Service.java', service('store', 'cache'))
        self.run_cli('baseline')
        status, output = self.run_cli('baseline')
        self.assertEqual(status, 2)
        self.assertIn('refusing overwrite', output)
        self.write('Service.java', service('store', 'fresh'))  # cache fixed, fresh added
        report = self.check()
        self.assertEqual(report['baseline']['stale'], 1)
        self.assertIn('baseline --prune', self.run_cli('check')[1])
        status, output = self.run_cli('baseline', '--prune')
        self.assertIn('Removed 1 fixed finding', output)
        stored = baseline.load(self.root).findings
        self.assertEqual(sum(e.count for e in stored.values()), 1)
        self.assertEqual(exit_code(self.check()), 1)  # 'fresh' was never absorbed

    def test_no_baseline_flag_reports_everything(self):
        self.write('Service.java', service('store'))
        self.run_cli('baseline')
        status, output = self.run_cli('check', '--no-baseline')
        self.assertEqual(status, 1)
        self.assertIn('Service.java', output)

    def test_incomplete_analysis_is_never_hidden(self):
        self.write('Service.java', service('store'))
        self.write('Broken.java', 'class Broken {')
        self.run_cli('baseline')
        self.assertEqual(exit_code(self.check()), 2)

    def test_invalid_baseline_files_fail_closed(self):
        self.write('Service.java', service('store'))
        bad = ['{', json.dumps({'version': 2, 'created': 'x', 'findings': {}}),
               json.dumps({'version': 1, 'created': 'x', 'findings': {'not-hex': {'rule': 'r', 'path': 'p', 'count': 1}}}),
               json.dumps({'version': 1, 'created': 'x', 'findings': {}, 'extra': 1})]
        for text in bad:
            (self.root / baseline.FILENAME).write_text(text)
            self.assertEqual(self.run_cli('check')[0], 2, text)
        (self.root / baseline.FILENAME).unlink()
        outside = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        self.addCleanup(os.unlink, outside.name)
        os.symlink(outside.name, self.root / baseline.FILENAME)
        self.assertEqual(self.run_cli('check')[0], 2)

    def test_reports_mark_baseline_state(self):
        self.write('Service.java', service('store'))
        self.run_cli('baseline')
        self.write('Other.java', service('cache').replace('Service', 'Other'))
        report = self.check()
        results = sarif(report)['runs'][0]['results']
        states = sorted((r['locations'][0]['physicalLocation']['artifactLocation']['uri'], r['baselineState']) for r in results)
        self.assertEqual(states, [('Other.java', 'new'), ('Service.java', 'unchanged')])
        self.assertTrue(all(len(r['partialFingerprints']['agentaccord/v1']) == 32 for r in results))
        html = dashboard(report)
        self.assertIn('Other.java', html)
        self.assertNotIn('Service.java:', html)
        self.assertIn('accepted by the baseline', html)

    def test_local_app_honors_baseline(self):
        self.write('Service.java', service('store'))
        self.run_cli('baseline')
        server = make_server(self.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        conn.request('POST', '/api/check', body='{}', headers={
            'Content-Type': 'application/json', 'X-AgentAccord-Token': server.token})
        result = json.loads(conn.getresponse().read())
        conn.close()
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['report']['baseline']['accepted'], 1)


if __name__ == '__main__':
    unittest.main()
