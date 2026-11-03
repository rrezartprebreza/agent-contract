import os
import tempfile
import unittest
from pathlib import Path
from agentaccord import configuration
from agentaccord.configuration import Policy, RulePolicy
from agentaccord.discovery import PARSER_JAVA, discover, java_version
from agentaccord.engine import exit_code, scan

RULES = {'spring.no-value': 'error'}
MODULE_IMPORT = 'import module java.base;\nclass Modern {}\n'


class JavaVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def detected(self, name, text):
        for path in self.root.iterdir():
            path.unlink() if path.is_file() or path.is_symlink() else None
        self.write(name, text)
        return java_version(self.root)

    def test_build_and_version_files(self):
        cases = [
            ('pom.xml', '<properties><maven.compiler.release>21</maven.compiler.release></properties>', 21),
            ('pom.xml', '<properties><java.version>17</java.version></properties>', 17),
            ('pom.xml', '<configuration><source>1.8</source></configuration>', 8),
            ('build.gradle.kts', 'java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }', 25),
            ('build.gradle.kts', 'kotlin { jvmToolchain(21) }', 21),
            ('build.gradle', "sourceCompatibility = '11'", 11),
            ('build.gradle', 'sourceCompatibility = JavaVersion.VERSION_1_8', 8),
            ('.java-version', '21.0.2\n', 21),
            ('.sdkmanrc', '# sdk env\njava=17.0.9-tem\n', 17),
            ('.tool-versions', 'nodejs 22.1.0\njava temurin-21.0.1+12.1\n', 21),
        ]
        for name, text, expected in cases:
            with self.subTest(name=name, text=text):
                self.assertEqual(self.detected(name, text), (expected, name))

    def test_release_wins_over_source_and_unknown_is_none(self):
        self.write('pom.xml', '<maven.compiler.source>17</maven.compiler.source><maven.compiler.release>21</maven.compiler.release>')
        self.assertEqual(java_version(self.root), (21, 'pom.xml'))
        self.assertEqual(self.detected('pom.xml', '<java.version>${jdk}</java.version>'), (None, None))

    def test_module_folder_and_links_are_not_followed(self):
        self.write('backend/pom.xml', '<java.version>21</java.version>')
        self.assertEqual(java_version(self.root), (21, 'backend/pom.xml'))
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / 'pom.xml').write_text('<java.version>8</java.version>')
        os.symlink(Path(outside.name) / 'pom.xml', self.root / 'pom.xml')
        self.assertEqual(java_version(self.root), (21, 'backend/pom.xml'))

    def test_discovery_reports_java_only_for_java_projects(self):
        self.write('.java-version', '17')
        self.assertIsNone(discover(self.root)['java'])
        self.write('src/App.java', 'class App {}')
        self.assertEqual(discover(self.root)['java'], dict(version=17, source='.java-version'))

    def test_report_states_version_and_policy_wins(self):
        self.write('pom.xml', '<java.version>17</java.version>')
        self.write('src/App.java', 'class App {}')
        self.assertEqual(scan(self.root, RULES)['java'], dict(version=17, source='pom.xml', parser=PARSER_JAVA))
        self.assertEqual(scan(self.root, RULES, java_version=21)['java'], dict(version=21, source='policy', parser=PARSER_JAVA))

    def test_newer_java_syntax_is_incomplete_with_reason(self):
        self.write('src/Modern.java', MODULE_IMPORT)
        report = scan(self.root, RULES, java_version=PARSER_JAVA + 1)
        self.assertEqual(exit_code(report), 2)
        self.assertIn(f'targets Java {PARSER_JAVA + 1}', report['skipped'][0]['reason'])
        self.assertTrue(any(f'targets Java {PARSER_JAVA + 1}' in item for item in report['limitations']))
        older = scan(self.root, RULES, java_version=21)
        self.assertNotIn('targets Java', older['skipped'][0]['reason'])
        self.assertFalse(any('targets Java' in item for item in older['limitations']))

    def test_policy_round_trip(self):
        policy = Policy(rules={'spring.no-value': RulePolicy(approved=True)})
        configuration.save(self.root, policy)
        self.assertNotIn('java', (self.root / '.agentaccord.yml').read_text())
        configuration.save(self.root, policy.model_copy(update=dict(java=configuration.JavaSettings(version=21))))
        self.assertIn('java:\n  version: 21', (self.root / '.agentaccord.yml').read_text())
        self.assertEqual(configuration.load(self.root).java.version, 21)
        for invalid in (3, '21', True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Policy.model_validate(dict(java=dict(version=invalid)))
