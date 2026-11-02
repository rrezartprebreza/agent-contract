"""Regressions found by running AgentAccord on real repositories (skills, docs, Lombok code)."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from agentaccord import configuration as config, instructions, python_checks
from agentaccord.cli import main
from agentaccord.engine import analyze, compile_exclude, exit_code, scan
from agentaccord.java_checks import JavaSyntaxError

RULES = {'spring.no-field-injection': 'error', 'spring.no-value': 'warning', 'spring.no-webmvctest': 'error'}
AUTOWIRED = 'org.springframework.beans.factory.annotation.Autowired'


class Repo:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class SymlinkTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.temp.cleanup)

    def test_irrelevant_symlink_does_not_make_analysis_incomplete(self):
        self.repo.write('src/A.java', 'class A {}')
        self.repo.write('docs/guide.txt', 'notes')
        os.symlink('docs/guide.txt', self.repo.root / 'guide-link.txt')
        os.symlink('docs', self.repo.root / 'docs-link')
        report = scan(self.repo.root, RULES)
        self.assertEqual(report['skipped'], [])
        self.assertEqual(exit_code(report), 0)

    def test_claude_md_linked_to_agents_md_is_covered_without_duplicates(self):
        self.repo.write('AGENTS.md', '# Rules\nUse field injection.\n')
        os.symlink('AGENTS.md', self.repo.root / 'CLAUDE.md')
        report = scan(self.repo.root, RULES)
        self.assertEqual(report['skipped'], [])
        self.assertEqual([(f['path'], f['rule']) for f in report['findings']],
                         [('AGENTS.md', 'spring.no-field-injection')])

    def test_relevant_symlink_leaving_the_repository_stays_incomplete(self):
        outside = Repo()
        self.addCleanup(outside.temp.cleanup)
        target = outside.write('AGENTS.md', 'Use field injection.\n')
        os.symlink(target, self.repo.root / 'AGENTS.md')
        report = scan(self.repo.root, RULES)
        self.assertEqual([s['path'] for s in report['skipped']], ['AGENTS.md'])
        self.assertEqual(exit_code(report), 2)

    def test_broken_relevant_symlink_stays_incomplete(self):
        os.symlink('missing.md', self.repo.root / 'AGENTS.md')
        self.assertEqual(exit_code(scan(self.repo.root, RULES)), 2)


class JavaResolutionTests(unittest.TestCase):
    def test_lombok_wildcard_value_is_not_spring_value(self):
        source = 'package com.example;\nimport lombok.*;\n@Value\nclass Money { int cents; }'
        self.assertEqual(analyze(source, 'Money.java', RULES), [])

    def test_unrelated_wildcard_still_finds_explicit_spring_import(self):
        source = f'package com.example;\nimport lombok.*;\nimport {AUTOWIRED};\nclass A {{ @Autowired Store store; }}'
        self.assertEqual([f['rule'] for f in analyze(source, 'A.java', RULES)], ['spring.no-field-injection'])

    def test_spring_wildcard_remains_incomplete(self):
        source = 'package com.example;\nimport org.springframework.beans.factory.annotation.*;\nclass A { @Autowired Store store; }'
        with self.assertRaisesRegex(JavaSyntaxError, 'wildcard or same-package'):
            analyze(source, 'A.java', RULES)

    def test_same_package_as_spring_remains_incomplete(self):
        source = 'package org.springframework.beans.factory.annotation;\nclass A { @Value("x") String s; }'
        with self.assertRaises(JavaSyntaxError):
            analyze(source, 'A.java', RULES)

    def test_snippet_without_package_or_imports_is_incomplete_with_guidance(self):
        with self.assertRaisesRegex(JavaSyntaxError, 'exclude example files'):
            analyze('class A { @Autowired Store store; }', 'A.java', RULES)


class ExcludeTests(unittest.TestCase):
    def test_glob_semantics(self):
        cases = {
            'examples/**': (['examples/a.java', 'examples/x/y/b.java'], ['src/examples.java', 'x/examples/a.java']),
            '**/examples/**': (['examples/a.java', 'skills/s/examples/bad.java'], ['skills/s/example/a.java']),
            'src/*.java': (['src/A.java'], ['src/x/A.java']),
            '**/*.generated.java': (['A.generated.java', 'a/b/A.generated.java'], ['A.java']),
            'docs/?.md': (['docs/a.md'], ['docs/ab.md']),
        }
        for pattern, (matching, other) in cases.items():
            regex = compile_exclude(pattern)
            for rel in matching:
                self.assertTrue(regex.fullmatch(rel), (pattern, rel))
            for rel in other:
                self.assertFalse(regex.fullmatch(rel), (pattern, rel))

    def test_invalid_patterns_are_rejected(self):
        for pattern in ['', '/abs/**', '../x', 'a/../b', 'a//b', 'a\\b', ' examples/**', 'x/./y']:
            with self.assertRaises(ValueError, msg=pattern):
                config.Policy(exclude=[pattern])
        with self.assertRaises(ValueError):
            config.Policy(exclude=['a/**', 'a/**'])

    def test_scan_excludes_and_reports_scope(self):
        repo = Repo()
        self.addCleanup(repo.temp.cleanup)
        repo.write('skills/testing/examples/bad.java', 'class A { @Autowired Store store; }')
        repo.write('src/A.java', f'package a;\nimport {AUTOWIRED};\nclass A {{ @Autowired Store store; }}')
        report = scan(repo.root, RULES, ['**/examples/**'])
        self.assertEqual(report['excluded_files'], 1)
        self.assertEqual(report['skipped'], [])
        self.assertEqual([f['path'] for f in report['findings']], ['src/A.java'])
        self.assertTrue(any('excluded by the approved policy scope' in item for item in report['limitations']))

    def test_policy_round_trip_and_unchanged_files_without_excludes(self):
        repo = Repo()
        self.addCleanup(repo.temp.cleanup)
        config.save(repo.root, config.Policy(rules={'spring.no-value': config.RulePolicy(approved=True)}))
        self.assertNotIn('exclude', (repo.root / '.agentaccord.yml').read_text())
        config.save(repo.root, config.Policy(exclude=['examples/**']))
        self.assertEqual(config.load(repo.root).exclude, ['examples/**'])


class InstructionTests(unittest.TestCase):
    def test_nested_list_items_are_instructions_not_code(self):
        source = '# Testing\n1. Controllers:\n    - Use @WebMvcTest for controller tests.\n'
        self.assertEqual([f['line'] for f in instructions.analyze(source, 'AGENTS.md', RULES)], [3])

    def test_indented_code_outside_lists_is_still_excluded(self):
        source = 'Example:\n\n    Use @WebMvcTest here.\n'
        self.assertEqual(instructions.analyze(source, 'AGENTS.md', RULES), [])

    def test_paragraph_after_list_ends_list_context(self):
        source = '- Testing notes\n\nPlain paragraph.\n\n    Use @WebMvcTest in this snippet.\n'
        self.assertEqual(instructions.analyze(source, 'AGENTS.md', RULES), [])


class RobustnessTests(unittest.TestCase):
    def test_python_column_with_form_feed_line(self):
        source = 'x = 1\n\x0c\ndef f(a=[]):\n    return a\n'
        result = python_checks.analyze(source, 'f.py', {'python.no-mutable-defaults': 'error'})
        self.assertEqual([(f['line'], f['column']) for f in result], [(3, source.split('\n')[2].index('[') + 1)])

    def test_internal_error_exits_2_not_violation_code(self):
        repo = Repo()
        self.addCleanup(repo.temp.cleanup)
        config.save(repo.root, config.Policy(rules={'spring.no-value': config.RulePolicy(approved=True)}))
        output = io.StringIO()
        with mock.patch('agentaccord.cli.scan', side_effect=RuntimeError('boom')), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status = main(['check', str(repo.root)])
        self.assertEqual(status, 2)
        self.assertIn('internal error', output.getvalue())


if __name__ == '__main__':
    unittest.main()


class ExampleTests(unittest.TestCase):
    """Fenced code in instruction files teaches agents; labelled counter-examples do not."""

    def findings(self, source):
        return [(f['rule'], f['line'], f['severity'], f['confidence'])
                for f in instructions.analyze(source, 'SKILL.md', RULES) if f['confidence'] == 'example']

    def test_unlabelled_java_example_is_a_nonblocking_conflict(self):
        source = '## Controller slices\n\n```java\n@WebMvcTest(OrderController.class)\nclass OrderControllerTest {}\n```\n'
        self.assertEqual(self.findings(source), [('spring.no-webmvctest', 4, 'warning', 'example')])

    def test_labelled_counter_examples_are_ignored(self):
        for label_before, first_line in [('❌ Wrong:', ''), ('Avoid this:', ''), ('', '// ❌ BAD — field injection'),
                                         ('### Before', ''), ('Bad example', '')]:
            source = f'{label_before}\n\n```java\n{first_line}\nclass A {{ @Autowired Store store; }}\n```\n'
            self.assertEqual(self.findings(source), [], (label_before, first_line))

    def test_good_label_beats_an_earlier_bad_label(self):
        source = 'Avoid field injection. Instead:\n\n```java\n// ✅ GOOD\nclass A { @Autowired Store store; }\n```\n'
        self.assertEqual([f[0] for f in self.findings(source)], ['spring.no-field-injection'])

    def test_snippets_without_class_and_other_languages(self):
        fields_only = 'Use this:\n\n```java\n@Autowired\nprivate Store store;\n```\n'
        self.assertEqual([f[1] for f in self.findings(fields_only)], [4])
        yaml_block = '```yaml\nvalue: "@Value(x)"\n```\n'
        prose_block = '```\nUse @Value.\n```\n'
        self.assertEqual(self.findings(yaml_block) + self.findings(prose_block), [])

    def test_lombok_value_without_arguments_is_not_spring_value(self):
        source = '```java\n@Value\nclass Money { int cents; }\n```\n```java\nclass A { @Value("${x}") String x; }\n```\n'
        self.assertEqual(self.findings(source), [('spring.no-value', 6, 'warning', 'example')])

    def test_constructor_injection_example_passes(self):
        source = '```java\nclass A {\n  private final Store store;\n  @Autowired A(Store store) { this.store = store; }\n}\n```\n'
        self.assertEqual(self.findings(source), [])


class TestClassInjectionTests(unittest.TestCase):
    def test_field_injection_in_test_classes_is_exempt(self):
        imports = f'package a;\nimport {AUTOWIRED};\n'
        spring_test = imports + 'import org.springframework.boot.test.context.SpringBootTest;\n@SpringBootTest\nclass ITest { @Autowired Store store; }'
        junit_test = imports + 'import org.junit.jupiter.api.Test;\nclass UTest { @Autowired Store store; @Test void works() {} }'
        nested = imports + 'class Outer { @org.junit.jupiter.api.Nested class Inner { @Autowired Store store; } }'
        for source in (spring_test, junit_test, nested):
            self.assertEqual(analyze(source, 'T.java', RULES), [])

    def test_production_class_is_still_flagged(self):
        source = f'package a;\nimport {AUTOWIRED};\nclass Service {{ @Autowired Store store; void test() {{}} }}'
        self.assertEqual([f['rule'] for f in analyze(source, 'Service.java', RULES)], ['spring.no-field-injection'])


CUSTOM = {'custom.no-lombok-data': {'title': 'Explicit data classes', 'annotation': 'lombok.Data',
                                    'guidance': 'Do not use @Data. Use records or explicit accessors.'},
          'custom.no-field-inject': {'title': 'No Guice field injection', 'annotation': 'com.google.inject.Inject',
                                     'guidance': 'Inject Guice dependencies through constructors.', 'target': 'field'}}


class CustomRuleTests(unittest.TestCase):
    def policy(self, approved=True):
        return config.Policy.model_validate({'version': 1, 'custom': CUSTOM, 'rules': {
            rule: {'approved': approved, 'severity': 'error'} for rule in CUSTOM}})

    def test_validation(self):
        bad = [
            {'custom': {'no-prefix': CUSTOM['custom.no-lombok-data']}},
            {'custom': {'custom.Bad_Id': CUSTOM['custom.no-lombok-data']}},
            {'custom': {'custom.x': {**CUSTOM['custom.no-lombok-data'], 'annotation': 'Data'}}},
            {'custom': {'custom.x': {**CUSTOM['custom.no-lombok-data'], 'unknown': 1}}},
            {'rules': {'custom.undefined': {'approved': True}}},
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=data):
                config.Policy.model_validate({'version': 1, **data})

    def test_unapproved_custom_rules_do_not_run(self):
        self.assertEqual(self.policy(approved=False).active(), {})

    def test_code_instruction_and_example_checks(self):
        policy = self.policy()
        rules, catalog = policy.active(), policy.catalog()
        code = 'package a;\nimport lombok.Data;\nimport com.google.inject.Inject;\n@Data\nclass A { @Inject Store store; @Inject A(Store s) {} }'
        self.assertEqual(sorted((f['rule'], f['line']) for f in analyze(code, 'A.java', rules, catalog)),
                         [('custom.no-field-inject', 5), ('custom.no-lombok-data', 4)])
        unrelated = 'package a;\nimport my.Data;\n@Data\nclass A {}'
        self.assertEqual(analyze(unrelated, 'A.java', rules, catalog), [])
        doc = '- Use @Data for DTOs.\n\n```java\n@Data\nclass Dto { String name; }\n```\n'
        found = instructions.analyze(doc, 'AGENTS.md', rules, catalog)
        self.assertEqual([(f['line'], f['confidence']) for f in found], [(1, 'pattern'), (4, 'example')])

    def test_guidance_and_scan_use_custom_rules(self):
        policy = self.policy()
        self.assertIn('Do not use @Data. Use records or explicit accessors. [custom.no-lombok-data; error]',
                      instructions.guidance(policy.active(), policy.catalog()))
        repo = Repo()
        self.addCleanup(repo.temp.cleanup)
        repo.write('src/A.java', 'package a;\nimport lombok.Data;\n@Data\nclass A {}')
        report = scan(repo.root, policy.active(), (), policy.catalog())
        self.assertEqual([f['rule'] for f in report['findings']], ['custom.no-lombok-data'])

    def test_save_round_trip_is_minimal(self):
        repo = Repo()
        self.addCleanup(repo.temp.cleanup)
        config.save(repo.root, self.policy())
        text = (repo.root / '.agentaccord.yml').read_text()
        self.assertNotIn('remediation', text)
        self.assertEqual(text.count('target'), 1)
        self.assertEqual(config.load(repo.root), self.policy())

    def test_cli_lists_custom_rules(self):
        repo = Repo()
        self.addCleanup(repo.temp.cleanup)
        config.save(repo.root, self.policy())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['rules', str(repo.root)]), 0)
        self.assertIn('custom.no-lombok-data: Do not use @Data. Use records or explicit accessors. (custom)', output.getvalue())
