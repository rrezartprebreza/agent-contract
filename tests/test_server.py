import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from agentcontract.server import make_server

class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.server=make_server(self.root)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()
    def request(self, method, route, body=None, token=True, extra=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'Content-Type':'application/json'}
        if token: headers['X-AgentContract-Token']=self.server.token
        if extra: headers.update(extra)
        conn.request(method,route,body=json.dumps(body) if body is not None else None,headers=headers)
        response=conn.getresponse(); content=response.read().decode(); status=response.status; conn.close()
        return status,content
    def test_static_and_api_authentication(self):
        self.assertEqual(self.request('GET','/')[0],200)
        self.assertEqual(self.request('GET','/api/state',token=False)[0],403)
        self.assertEqual(self.request('GET','/api/state',extra={'Origin':'https://untrusted.example'})[0],403)
        self.assertEqual(self.request('GET','/api/state',extra={'Host':'attacker.example'})[0],403)
        self.assertEqual(self.request('GET','/../../etc/passwd')[0],404)
    def test_full_policy_scan_guidance_flow(self):
        status,data=self.request('GET','/api/state'); self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['policy']['rules'],{})
        policy={'version':1,'rules':{'spring.no-field-injection':{'approved':True,'enabled':True,'severity':'error'}}}
        self.assertEqual(self.request('POST','/api/policy',policy)[0],200)
        (self.root/'A.java').write_text('class A { @org.springframework.beans.factory.annotation.Autowired Store store; }')
        (self.root/'AGENTS.md').write_text('# Keep this\nUse field injection.\n')
        status,data=self.request('POST','/api/check',{}); report=json.loads(data)
        self.assertEqual(status,200); self.assertEqual(report['exit_code'],1)
        self.assertEqual(len(report['report']['findings']),2)
        self.assertEqual(self.request('POST','/api/guidance',{})[0],200)
        self.assertIn('# Keep this', (self.root/'AGENTS.md').read_text())
        self.assertEqual(self.request('POST','/api/export',{'format':'html'})[0],200)
    def test_invalid_payload_cannot_write_policy(self):
        self.assertEqual(self.request('POST','/api/policy',{'version':1,'rules':{'typo':{}}})[0],400)
        self.assertFalse((self.root/'.agentcontract.yml').exists())
        self.assertEqual(self.request('POST','/api/policy',[],token=False)[0],403)
        self.assertEqual(self.request('POST','/api/guidance',{})[0],400)
    def test_no_approved_rules_is_incomplete(self):
        self.request('POST','/api/policy',{'version':1,'rules':{}})
        status,data=self.request('POST','/api/check',{})
        self.assertEqual(status,200); self.assertEqual(json.loads(data)['exit_code'],2)
    def test_policy_scope_survives_save_and_applies_to_checks(self):
        policy={'version':1,'exclude':['examples/**'],'rules':{'spring.no-field-injection':{'approved':True,'enabled':True,'severity':'error'}}}
        self.assertEqual(self.request('POST','/api/policy',policy)[0],200)
        self.assertEqual(json.loads(self.request('GET','/api/state')[1])['policy']['exclude'],['examples/**'])
        (self.root/'examples').mkdir()
        (self.root/'examples'/'Bad.java').write_text('class Bad { @Autowired Store store; }')
        status,data=self.request('POST','/api/check',{}); result=json.loads(data)
        self.assertEqual(result['exit_code'],0); self.assertEqual(result['report']['excluded_files'],1)
    def test_custom_rules_are_listed_and_enforced(self):
        custom={'custom.no-lombok-data':{'title':'Explicit data classes','annotation':'lombok.Data','guidance':'Do not use @Data.'}}
        policy={'version':1,'custom':custom,'rules':{'custom.no-lombok-data':{'approved':True,'enabled':True,'severity':'error'}}}
        self.assertEqual(self.request('POST','/api/policy',policy)[0],200)
        state=json.loads(self.request('GET','/api/state')[1])
        self.assertEqual(state['rules']['custom.no-lombok-data']['title'],'Explicit data classes')
        (self.root/'A.java').write_text('package a;\nimport lombok.Data;\n@Data\nclass A {}')
        report=json.loads(self.request('POST','/api/check',{})[1])
        self.assertEqual(report['exit_code'],1); self.assertEqual(report['report']['findings'][0]['rule'],'custom.no-lombok-data')
