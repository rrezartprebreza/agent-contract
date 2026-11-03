import json
import unittest
from pydantic import ValidationError
from agentaccord.quickcheck import check
from agentaccord.python_checks import analyze
from agentaccord.json_checks import analyze as json_analyze
import test_server


class QuickTests(unittest.TestCase):
    def run_check(self, name, content, rules):
        return check({'files':[{'name':name,'content':content}], 'rules':rules})

    def test_snippet_and_markdown_use_original_names(self):
        for name, content in [('sample.java', 'class A { @Value("x") String x; }'),
                              ('notes.md', '```java\nclass A { @Value("x") String x; }\n```')]:
            result=self.run_check(name,content,['spring.no-value'])
            self.assertEqual(result['exit_code'],0)
            self.assertEqual(result['report']['findings'][0]['path'],name)
            self.assertEqual(result['report']['findings'][0]['severity'],'warning')

    def test_explicit_rules_only_and_mixed_languages(self):
        result=check({'files':[{'name':'a.py','content':'try:\n pass\nexcept:\n pass'},
                               {'name':'a.json','content':'{"x":1,"x":2}'}],
                      'rules':['python.no-bare-except','json.no-duplicate-keys']})
        self.assertEqual(result['exit_code'],1)
        self.assertEqual(result['report']['analyzed_files'],2)
        self.assertEqual(len(result['report']['findings']),2)
        self.assertFalse(analyze('try:\n pass\nexcept ValueError:\n pass','a.py',{'python.no-bare-except':'error'}))
        self.assertFalse(analyze('try:\n pass\nexcept:\n pass','a.py',{'python.require-type-hints':'error'}))

    def test_unsupported_and_wrong_language_are_not_clean(self):
        for name in ['a.ts','a.py']:
            result=self.run_check(name,'example',['json.no-duplicate-keys'])
            self.assertEqual(result['exit_code'],2)
            self.assertEqual(len(result['report']['skipped']),1)

    def test_invalid_syntax_incomplete(self):
        for name,source,rule in [('a.json','{"a":}', 'json.no-duplicate-keys'),
                                  ('a.json','{"a": NaN}', 'json.no-duplicate-keys'),
                                  ('a.java','class {','spring.no-value'),
                                  ('a.py','def :','python.no-bare-except')]:
            self.assertEqual(self.run_check(name,source,[rule])['exit_code'],2)

    def test_json_nested_keys_and_escaped_names(self):
        result=json_analyze('{"a": {"x":1,"\\u0078":2},"b":{"x":3}}','config.json',{'json.no-duplicate-keys':'warning'})
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['evidence'],'x')
        self.assertEqual(result[0]['line'],1)
        self.assertFalse(json_analyze('{"a":{"x":1},"b":{"x":2}}','config.json',{'json.no-duplicate-keys':'error'}))

    def test_fenced_python_and_json_have_source_locations(self):
        for language,content,rule in [('python','try:\n pass\nexcept:\n pass','python.no-bare-except'),
                                      ('json','{"a":1,"a":2}','json.no-duplicate-keys')]:
            result=self.run_check('SKILL.md', '# Example\n```'+language+'\n'+content+'\n```',[rule])
            self.assertEqual(result['exit_code'],0)
            finding=result['report']['findings'][0]
            self.assertEqual(finding['severity'],'warning')
            self.assertEqual(finding['line'],5 if language=='python' else 3)
            bad=self.run_check('SKILL.md','```'+language+'\n{invalid!\n```',[rule])
            self.assertEqual(bad['exit_code'],2)
            labelled=self.run_check('SKILL.md','# Bad\n```'+language+'\n'+content+'\n```',[rule])
            self.assertFalse(labelled['report']['findings'])

    def test_json_baseline_identity_changes_with_document(self):
        first=self.run_check('a.json','{\n"a":1,"a":2\n}',['json.no-duplicate-keys'])
        changed=self.run_check('a.json','{\n"b":1,"b":2\n}',['json.no-duplicate-keys'])
        self.assertNotEqual(first['report']['findings'][0]['fingerprint'],changed['report']['findings'][0]['fingerprint'])

    def test_request_validation(self):
        for name in ['../secret','/tmp/x','a\\b','x:y','bad\x00name']:
            with self.assertRaises(ValidationError):self.run_check(name,'x',['spring.no-value'])
        for rules in [[],['unknown'],['spring.no-value','spring.no-value']]:
            with self.assertRaises(ValidationError):self.run_check('a.java','x',rules)
        with self.assertRaises(ValidationError):self.run_check('a.java','é'*60000,['spring.no-value'])
        with self.assertRaises(ValidationError):check({'files':[{'name':'a.py','content':''}]*2,'rules':['python.no-bare-except']})


class QuickHTTPTests(unittest.TestCase):
    setUp = test_server.AppTests.setUp
    tearDown = test_server.AppTests.tearDown
    request = test_server.AppTests.request
    def test_quick_check_is_authenticated_and_does_not_write_repository(self):
        payload={'files':[{'name':'demo.java','content':'class A { @Value("x") String x; }'}], 'rules':['spring.no-value']}
        self.assertEqual(self.request('POST','/api/quick-check',payload,token=False)[0],403)
        self.assertEqual(self.request('POST','/api/quick-check',payload,extra={'Origin':'https://other.example'})[0],403)
        status,body=self.request('POST','/api/quick-check',payload)
        self.assertEqual(status,200)
        self.assertEqual(len(json.loads(body)['report']['findings']),1)
        self.assertEqual(list(self.root.iterdir()),[])
        payload['files'][0]['content']='// padding\n'*4000+'class A {}'
        self.assertEqual(self.request('POST','/api/quick-check',payload)[0],200)
        payload['files'][0]['name']='../escape.java'
        self.assertEqual(self.request('POST','/api/quick-check',payload)[0],400)
