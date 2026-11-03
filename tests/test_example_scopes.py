"""Regression cases from the Spring Boot Skills trial and scope boundary cases."""
import tempfile
import unittest
from pathlib import Path
from agentaccord.configuration import Policy, RulePolicy, Examples, save, load
from agentaccord.engine import scan, analyze, exit_code
from agentaccord.java_checks import analyze_snippet
from agentaccord.instructions import analyze as instruction_check

VALUE = 'spring.no-value'
FIELD = 'spring.no-field-injection'


class ExampleScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, source):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        return path

    def check(self, policy):
        return scan(self.root, policy.active(), policy.exclude, policy.catalog(), policy.examples)

    def test_import_free_examples_are_opt_in_and_non_blocking(self):
        self.write('examples/good.java', 'class Service { @Autowired Store store; }')
        policy = Policy(rules={FIELD: RulePolicy(approved=True)})
        self.assertEqual(exit_code(self.check(policy)), 2)
        policy.examples = Examples(java=['examples/**/*.java'])
        report = self.check(policy)
        self.assertEqual(exit_code(report), 0)
        self.assertEqual(report['example_files'], 1)
        finding, = report['findings']
        self.assertEqual((finding['line'], finding['kind'], finding['confidence'], finding['severity']),
                         (1, 'example', 'example', 'warning'))

    def test_counter_examples_only_omitted_inside_explicit_example_scope(self):
        self.write('examples/bad.java', 'class Bad { @Autowired Store store; }')
        self.write('src/bad.java', 'class Bad { @Autowired Store store; }')
        policy = Policy(rules={FIELD: RulePolicy(approved=True)},
                        examples=Examples(java=['examples/**'], counter_examples=['**/bad.java']))
        report = self.check(policy)
        self.assertEqual(report['counter_example_files'], ['examples/bad.java'])
        self.assertEqual([s['path'] for s in report['skipped']], ['src/bad.java'])
        self.assertEqual(exit_code(report), 2)

    def test_broken_example_remains_incomplete(self):
        self.write('example.java', 'class Broken {')
        policy = Policy(rules={VALUE: RulePolicy(approved=True)}, examples=Examples(java=['*.java']))
        report = self.check(policy)
        self.assertEqual(exit_code(report), 2)
        self.assertEqual(report['example_files'], 0)
        self.assertIn('could not be parsed', report['skipped'][0]['reason'])

    def test_rule_exclusion_does_not_hide_other_rules(self):
        self.write('src/A.java', 'class A { @org.springframework.beans.factory.annotation.Value("x") String s; '
                   '@org.springframework.beans.factory.annotation.Autowired Store store; }')
        policy = Policy(rules={VALUE: RulePolicy(approved=True, exclude=['src/**']),
                              FIELD: RulePolicy(approved=True, include=['src/**'])})
        report = self.check(policy)
        self.assertEqual([f['rule'] for f in report['findings']], [FIELD])
        self.assertEqual(report['rule_scope_omissions'], [{'path': 'src/A.java', 'rules': [VALUE]}])
        self.assertEqual(exit_code(report), 1)

    def test_batch_exception_is_narrow_and_opt_in(self):
        expressions = ['"#{jobParameters[\'status\']}"', '"\u0024{service.secret}"',
                       '"#{jobParameters[\'status\'].toString()}"', '"prefix#{jobParameters[\'status\']}"']
        policy = Policy(rules={VALUE: RulePolicy(approved=True, allow_job_parameters=True)})
        for i, expression in enumerate(expressions):
            source = f'import org.springframework.beans.factory.annotation.Value; class A {{ void reader(@Value({expression}) String value) {{}} }}'
            with self.subTest(expression=expression):
                self.assertEqual(len(analyze(source, 'A.java', policy.active(), policy.catalog())), 0 if i == 0 else 1)
                self.assertEqual(len(analyze_snippet(source, policy.active(), policy.catalog())), 0 if i == 0 else 1)
                self.assertEqual(len(analyze(source, 'A.java', policy.active())), 1)
        source = 'class A { void reader(@Value(value = "#{jobParameters[\'status\']}") String s) {} }'
        self.assertEqual(analyze_snippet(source, policy.active(), policy.catalog()), [])

    def test_snippets_respect_explicit_types_and_local_annotations(self):
        for source in ['import other.Value; class A { @Value("x") String s; }',
                       'class A { @other.Value("x") String s; }',
                       '@interface Value { String value(); } class A { @Value("x") String s; }',
                       '@Value class A {}']:
            with self.subTest(source=source):
                self.assertEqual(analyze_snippet(source, {VALUE: 'error'}), [])
        self.assertEqual(len(analyze_snippet('@Value("x") String s;', {VALUE: 'error'})), 1)

    def test_counterexample_fences_and_batch_exception(self):
        policy = Policy(rules={VALUE: RulePolicy(approved=True, allow_job_parameters=True)})
        for label, expected in [('Bad', 0), ('Recommended', 1)]:
            source = f'# {label}\n\n```java\n@Value("x") String value;\n```'
            self.assertEqual(len(instruction_check(source, 'SKILL.md', policy.active(), policy.catalog())), expected)
        source = '```java\n@Value("#{jobParameters[\'status\']}") String status;\n```'
        self.assertEqual(instruction_check(source, 'SKILL.md', policy.active(), policy.catalog()), [])

    def test_policy_validation_and_roundtrip(self):
        policy = Policy(rules={VALUE: RulePolicy(approved=True, include=['src/**'],
                                                exclude=['src/test/**'], allow_job_parameters=True)},
                        examples=Examples(java=['examples/**'], counter_examples=['examples/bad*']))
        save(self.root, policy)
        self.assertEqual(load(self.root), policy)
        for field in ('include', 'exclude'):
            for pattern in ('../outside', '/absolute', 'a\\b', ' a', 'a//b'):
                with self.subTest(field=field, pattern=pattern), self.assertRaises(ValueError):
                    RulePolicy(**{field: [pattern]})
        with self.assertRaises(ValueError):
            Policy(rules={FIELD: RulePolicy(allow_job_parameters=True)})
        with self.assertRaises(ValueError):
            Examples(java=['a', 'a'])
        with self.assertRaises(ValueError):
            RulePolicy(allow_job_parameters='true')

    def test_symlink_to_excluded_target_is_incomplete(self):
        target = self.write('excluded/A.java', 'class A {}')
        (self.root / 'A.java').symlink_to(target)
        policy = Policy(rules={VALUE: RulePolicy(approved=True)}, exclude=['excluded/**'])
        self.assertEqual(exit_code(self.check(policy)), 2)

    def test_catalog_does_not_modify_builtins(self):
        scoped = Policy(rules={VALUE: RulePolicy(include=['src/**'], allow_job_parameters=True)})
        scoped.catalog()
        plain = Policy(rules={VALUE: RulePolicy(approved=True)}).catalog()
        self.assertNotIn('allow_job_parameters', plain[VALUE])
        self.assertEqual(plain[VALUE]['include'], [])

    def test_cli_loads_example_configuration(self):
        import contextlib
        import io
        import json
        from agentaccord.cli import main
        self.write('A.java', '@Value("x") String s;')
        save(self.root, Policy(rules={VALUE: RulePolicy(approved=True)}, examples=Examples(java=['*.java'])))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(['check', str(self.root), '--format', 'json'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['example_files'], 1)

    def test_symlink_cycle_is_reported(self):
        (self.root / 'A.java').symlink_to('B.java')
        (self.root / 'B.java').symlink_to('A.java')
        report = self.check(Policy(rules={VALUE: RulePolicy(approved=True)}))
        self.assertEqual(exit_code(report), 2)
        self.assertEqual(len(report['skipped']), 2)

    def test_java_is_not_parsed_when_only_python_rule_applies(self):
        self.write('A.java', 'class Broken {')
        policy = Policy(rules={VALUE: RulePolicy(approved=True, include=['src/**']),
                              'python.no-mutable-defaults': RulePolicy(approved=True)})
        report = self.check(policy)
        self.assertEqual(report['skipped'], [])
        self.assertEqual(report['analyzed_files'], 0)
    def test_findings_capture_policy_and_bounded_source_evidence(self):
        self.write('A.java','class A { @org.springframework.beans.factory.annotation.Value("x") String x; }'+' '*600)
        report=self.check(Policy(rules={VALUE:RulePolicy(approved=True,include=['*.java'])}))
        finding,=report['findings']
        self.assertEqual(finding['policy']['include'],['*.java'])
        self.assertEqual(finding['policy']['severity'],'error')
        self.assertEqual(len(finding['source_line']),501)
        self.assertIn('@org.springframework',finding['source_line'])
        self.assertNotIn('scope_files',report)
