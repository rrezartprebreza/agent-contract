import io
import os
import json
import stat
import tempfile
import unittest
import zipfile
import threading
import http.client
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.request import Request
from agentaccord.projects import OUTSIDE_LINK, github_repository, unpack, prepare, GitHubRedirects, download
from agentaccord.engine import exit_code, scan
from agentaccord.server import make_server
import test_server


def symlink(name):
    info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16
    return info


def archive(items):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as output:
        for name,content in items:
            output.writestr(name,content)
    return stream.getvalue()


class ProjectTests(unittest.TestCase):
    def test_urls_are_restricted_to_repository_roots(self):
        self.assertEqual(github_repository('https://github.com/owner/project.git/'),'owner/project')
        for url in ['http://github.com/o/r','https://github.com.evil/o/r','https://u:p@github.com/o/r',
                    'https://github.com/o/r/tree/main','https://github.com/o/r?q=x',
                    'https://github.com/o/r#secret','file:///tmp/x','https://github.com/o/..',
                    'https://github.com:443/o/r']:
            with self.subTest(url=url),self.assertRaises(ValueError):github_repository(url)

    def test_redirect_does_not_allow_local_or_non_github_hosts(self):
        handler=GitHubRedirects()
        for url in ['http://codeload.github.com/o/r','https://127.0.0.1/x','https://example.com/x']:
            with self.assertRaises(ValueError):handler.redirect_request(Request('https://api.github.com/x'),None,302,'',{},url)

    def test_archive_preserves_files_without_running_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            unpack(archive([('project-sha/SKILL.md','# Instructions'),('project-sha/run.sh','exit 42')]),root)
            self.assertEqual((root/'SKILL.md').read_text(),'# Instructions')
            self.assertEqual((root/'run.sh').read_text(),'exit 42')
            self.assertFalse((root/'run.sh').stat().st_mode & stat.S_IXUSR)

    def test_archive_rejects_unsafe_paths_and_links_before_writing(self):
        invalid=['project/../escape','/outside','project/a\\b','project/a:b','project//x','project/./x']
        for name in invalid:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):unpack(archive([('project/okay','text'),(name,'bad')]),Path(folder))
                self.assertEqual(list(Path(folder).iterdir()),[])
        with tempfile.TemporaryDirectory() as folder:
            # An absolute link is recreated broken, inside the snapshot -- never to the host path.
            unpack(archive([('project/',''),(symlink('project/link'),'/etc/passwd')]),Path(folder))
            link=Path(folder)/'link'
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link),OUTSIDE_LINK)
            self.assertFalse(link.exists())
        for items in [[('a/x','1'),('b/y','2')],[('a/X','1'),('a/x','2')]]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):unpack(archive(items),Path(folder))

    def test_archive_limits_and_invalid_zip(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch('agentaccord.projects.MAX_EXPANDED',2),self.assertRaises(ValueError):
                unpack(archive([('p/x','123')]),root)
            with patch('agentaccord.projects.MAX_ENTRIES',1),self.assertRaises(ValueError):
                unpack(archive([('p/x','1'),('p/y','2')]),root)
            with self.assertRaises(ValueError):unpack(b'not zip',root)

    def test_download_is_bounded_and_retains_tls_verification(self):
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value=io.BytesIO(b'abc')
        with patch('agentaccord.projects.build_opener',return_value=opener) as factory:
            self.assertEqual(download('o/r'),b'abc')
            handler=factory.call_args.args[1]
            self.assertTrue(handler._context.check_hostname)
            import ssl
            self.assertEqual(handler._context.verify_mode,ssl.CERT_REQUIRED)
            self.assertFalse(opener.open.call_args.args[0].has_header('Authorization'))
        opener.open.return_value.__enter__.return_value=io.BytesIO(b'abc')
        with patch('agentaccord.projects.build_opener',return_value=opener),patch('agentaccord.projects.MAX_DOWNLOAD',2):
            with self.assertRaises(ValueError):download('o/r')

    def test_local_path_and_snapshot_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root,temporary,metadata=prepare({'kind':'local','location':folder})
            self.assertEqual(root,Path(folder).resolve());self.assertIsNone(temporary)
            self.assertFalse(metadata['temporary'])
        with self.assertRaises(ValueError):prepare({'kind':'local','location':'relative'})
        with patch('agentaccord.projects.download',return_value=archive([('p-sha/SKILL.md','# Test')])):
            root,temporary,metadata=prepare({'kind':'github','location':'https://github.com/o/r'})
            self.assertTrue(metadata['temporary']);self.assertTrue((root/'SKILL.md').exists())
            temporary.cleanup();self.assertFalse(root.exists())


class ProjectHTTPTests(unittest.TestCase):
    setUp=test_server.AppTests.setUp
    tearDown=test_server.AppTests.tearDown
    request=test_server.AppTests.request

    def child_state(self, child):
        connection=http.client.HTTPConnection('127.0.0.1',child.server_port,timeout=5)
        connection.request('GET','/api/state',headers={'X-AgentAccord-Token':child.token})
        response=connection.getresponse();data=json.loads(response.read());connection.close()
        self.assertEqual(response.status,200)
        return data

    def test_local_connection_is_isolated_and_authenticated(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'SKILL.md').write_text('# New project')
            payload={'kind':'local','location':folder}
            self.assertEqual(self.request('POST','/api/open-project',payload,token=False)[0],403)
            self.assertEqual(self.request('POST','/api/open-project',payload,extra={'Origin':'https://evil.example'})[0],403)
            status,body=self.request('POST','/api/open-project',payload)
            self.assertEqual(status,200)
            child,_=self.server.children[0]
            self.assertNotEqual(child.token,self.server.token)
            self.assertEqual(json.loads(body)['url'],child.url)
            state=self.child_state(child)
            self.assertEqual(state['repository'],str(Path(folder).resolve()))
            self.assertEqual(state['discovery']['instructions'],['SKILL.md'])
            self.assertEqual(list(self.root.iterdir()),[])
            self.assertFalse((Path(folder)/'.agentaccord.yml').exists())

    def test_github_snapshot_is_cleaned_on_server_close(self):
        with patch('agentaccord.projects.download',return_value=archive([('p-sha/SKILL.md','# Skill')])):
            status,body=self.request('POST','/api/open-project',{'kind':'github','location':'https://github.com/o/r'})
        self.assertEqual(status,200)
        child,_=self.server.children[0]
        self.assertTrue(self.child_state(child)['project']['temporary'])
        root=Path(json.loads(body)['repository'])
        self.server.shutdown();self.server.server_close()
        self.assertFalse(root.exists())


class SnapshotLinkTests(unittest.TestCase):
    """Real skills repositories link plugin folders to shared skills; snapshots must accept them."""
    RULES={'spring.no-field-injection':'error'}

    def unpack_to(self, items):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        root=Path(folder.name); return root, unpack(archive(items),root)

    def test_links_inside_the_snapshot_are_kept_and_covered(self):
        root,stats=self.unpack_to([('repo/',''),('repo/skills/a/SKILL.md','Use field injection.\n'),
            ('repo/AGENTS.md','Use field injection.\n'),(symlink('repo/plugins/p/skills'),'../../skills'),
            (symlink('repo/CLAUDE.md'),'AGENTS.md')])
        self.assertEqual(stats,{'links':2,'outside_links':0})
        self.assertEqual(os.readlink(root/'plugins'/'p'/'skills'),'../../skills')
        report=scan(root.resolve(),self.RULES)
        self.assertEqual(report['skipped'],[])
        self.assertEqual(sorted(f['path'] for f in report['findings']),['AGENTS.md','skills/a/SKILL.md'])
        self.assertEqual(exit_code(report),1)

    def test_relevant_link_leaving_the_snapshot_makes_analysis_incomplete(self):
        root,stats=self.unpack_to([('repo/',''),('repo/A.java','class A {}'),(symlink('repo/AGENTS.md'),'../../../home/user/notes.md')])
        self.assertEqual(stats['outside_links'],1)
        self.assertEqual(os.readlink(root/'AGENTS.md'),OUTSIDE_LINK)
        report=scan(root.resolve(),self.RULES)
        self.assertEqual([s['path'] for s in report['skipped']],['AGENTS.md'])
        self.assertEqual(exit_code(report),2)

    def test_nothing_can_be_written_through_a_link(self):
        for items in [[('repo/',''),(symlink('repo/out'),'/tmp'),('repo/out/evil.txt','x')],
                      [('repo/',''),(symlink('repo/Out'),'docs'),('repo/out/evil.txt','x')]]:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError,'inside a symbolic link'):unpack(archive(items),Path(folder))
                self.assertEqual(list(Path(folder).iterdir()),[])

    def test_malformed_links_are_rejected(self):
        for target in ['a'*5000,'bad\x00target','dir\\x','']:
            with tempfile.TemporaryDirectory() as folder, self.subTest(target=target[:20]):
                with self.assertRaises(ValueError):unpack(archive([('repo/',''),(symlink('repo/link'),target)]),Path(folder))
