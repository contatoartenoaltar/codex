import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import app
import package_social_plugin as package
import social_mcp as mcp


class PluginPackageTests(unittest.TestCase):
    def responses(self, tools):
        return [io.BytesIO(json.dumps({'result': result}).encode()) for result in [
            {'protocolVersion': mcp.VERSION}, {'tools': tools},
            {'isError': False, 'structuredContent': {'accounts': []}}]]

    def tools(self):
        return [{'name': name, 'inputSchema': schema} for name, _, schema in mcp.TOOLS]

    def test_package_checks_only_reads_and_excludes_secret(self):
        token = 'synthetic-package-test-credential'
        opener = Mock()
        opener.open.side_effect = self.responses(self.tools())
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.build_opener', return_value=opener):
            destination = package.package('https://artenoaltar.pythonanywhere.com/mcp', token, Path(directory) / 'plugin.zip')
            with zipfile.ZipFile(destination) as archive:
                manifest = json.loads(archive.read('plugin.json'))
                self.assertEqual(manifest['version'], '0.2.0')
                for name in archive.namelist():
                    self.assertNotIn(token.encode(), archive.read(name))
                self.assertIn(b'social_schedule_draft', archive.read('skills/social-drafts/SKILL.md'))
        calls = [json.loads(call.args[0].data) for call in opener.open.call_args_list]
        self.assertEqual([c['method'] for c in calls], ['initialize', 'tools/list', 'tools/call'])
        self.assertEqual(calls[-1]['params']['name'], 'social_list_accounts')

    def test_old_endpoint_missing_schedule_is_not_packaged(self):
        opener = Mock()
        old = [t for t in self.tools() if t['name'] not in ('social_get_draft', 'social_schedule_draft')]
        opener.open.side_effect = self.responses(old)
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.build_opener', return_value=opener):
            destination = Path(directory) / 'plugin.zip'
            with self.assertRaises(ValueError):
                package.package('https://artenoaltar.pythonanywhere.com/mcp', 'synthetic-token', destination)
            self.assertFalse(destination.exists())
            self.assertEqual(opener.open.call_count, 2)

    def test_administrative_cli_reuses_configured_key_without_echo(self):
        opener = Mock()
        opener.open.side_effect = self.responses(self.tools())
        token = 'synthetic-local-file-package-credential'
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / '.local'
            private.mkdir()
            (private / 'mcp-key.txt').write_text(token)
            output = io.StringIO()
            with patch.object(app, 'DB', private / 'test.db'), patch('urllib.request.build_opener', return_value=opener), patch('sys.stdout', output), patch('sys.argv', ['package_social_plugin.py', 'https://artenoaltar.pythonanywhere.com/mcp', '--configured-key']):
                runpy.run_path(str(Path(package.__file__)), run_name='__main__')
            self.assertNotIn(token, output.getvalue())
            self.assertTrue((private / 'arte-no-altar-0.2.0.zip').is_file())
            self.assertFalse((private / 'test.db').exists())
