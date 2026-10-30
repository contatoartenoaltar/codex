import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import social_mcp as mcp
import wsgi
from test_publishing import jpeg


class SocialMCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.DB
        app.DB = Path(self.temp.name) / 'test.db'
        app.initialize()
        self.key = 'test-integration-key-with-32-characters'
        self.env = patch.dict(os.environ, {
            'ARTENOALTAR_MCP_KEY_SHA256': hashlib.sha256(self.key.encode()).hexdigest(),
            'ARTENOALTAR_MCP_ALLOWED_ORIGINS': ''})
        self.env.start()
        self.cache = patch('meta.status', return_value={'accounts': [
            {'id': '123', 'channel': 'Instagram', 'name': 'Arte no Altar', 'access_token': 'NEVER_RETURN'}],
            'access_token': 'NEVER_RETURN'})
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        self.env.stop()
        app.DB = self.old
        self.temp.cleanup()

    def http(self, message, key=None, origin=None, method='POST', **extra):
        raw = json.dumps(message).encode()
        env = {'PATH_INFO': '/mcp', 'REQUEST_METHOD': method, 'HTTP_HOST': 'localhost',
               'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)),
               'HTTP_ACCEPT': 'application/json, text/event-stream',
               'HTTP_AUTHORIZATION': 'Bearer ' + (self.key if key is None else key),
               'wsgi.input': io.BytesIO(raw)}
        if origin is not None:
            env['HTTP_ORIGIN'] = origin
        env.update(extra)
        response = {}
        def start(status, headers):
            response['status'] = int(status.split()[0])
        response['body'] = b''.join(wsgi.application(env, start))
        return response

    def call(self, name, arguments=None):
        result = self.http({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                            'params': {'name': name, 'arguments': arguments or {}}})
        self.assertEqual(result['status'], 200)
        return json.loads(result['body'])['result']

    def draft(self):
        return {'account_id': '123', 'channel': 'Instagram', 'format': 'feed_photo',
                'caption': 'Conteúdo aprovado', 'confirmed': True,
                'image_base64': base64.b64encode(jpeg()).decode(),
                'idempotency_key': 'integration-test-001',
                'desired_at': '2026-11-05T09:00:00-03:00'}

    def test_protocol_and_auth_fail_closed(self):
        message = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                   'params': {'protocolVersion': '2025-06-18'}}
        self.assertEqual(self.http(message, key='wrong')['status'], 401)
        self.assertEqual(self.http(message, origin='https://evil.example')['status'], 403)
        self.assertEqual(self.http(message)['status'], 200)
        self.assertEqual(self.http(message, method='GET')['status'], 405)
        self.assertEqual(self.http(message, HTTP_MCP_PROTOCOL_VERSION='unsupported')['status'], 400)
        self.assertEqual(self.http(message, HTTP_ACCEPT='application/json')['status'], 406)
        notification = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
        self.assertEqual(self.http(notification), {'status': 202, 'body': b''})
        with patch.dict(os.environ, {'ARTENOALTAR_MCP_KEY_SHA256': ''}):
            self.assertEqual(self.http(message)['status'], 401)

    def test_data_isolation_and_unknown_tools(self):
        result = self.call('social_list_accounts')
        self.assertNotIn('NEVER_RETURN', json.dumps(result))
        self.assertTrue(self.call('financial_list')['isError'])
        self.assertTrue(self.call('social_list_accounts', {'table': 'orders'})['isError'])
        self.assertTrue(self.call('social_list_recent_content', {'account_id': '456'})['isError'])

    def test_confirmed_import_idempotency_and_receipt(self):
        data = self.draft()
        with patch('publishing.publish', side_effect=AssertionError('must not publish')):
            first = self.call('social_import_draft', data)
            self.assertFalse(first['isError'], first)
            receipt = first['structuredContent']
            self.assertEqual(first, self.call('social_import_draft', data))
            self.assertEqual(self.call('social_get_operation', {'operation_id': receipt['id']})['structuredContent'], receipt)
            changed = data | {'caption': 'Outra legenda'}
            self.assertTrue(self.call('social_import_draft', changed)['isError'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 1)
            self.assertEqual(c.execute('SELECT publish_status FROM posts').fetchone()[0], 'draft')
            self.assertEqual(c.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
        self.assertEqual(len(list((app.DB.parent / 'media').glob('*.jpg'))), 1)

    def test_invalid_imports_do_not_create_posts(self):
        for change in [{'confirmed': False}, {'account_id': '456'}, {'format': 'story'},
                       {'image_base64': 'broken'}, {'desired_at': '2026-11-05T09:00:00'},
                       {'desired_at': '2026-11-05T09:00:00+00:00'}, {'caption': '   '},
                       {'arbitrary_path': '/private'}]:
            self.assertTrue(self.call('social_import_draft', self.draft() | change)['isError'], change)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 0)

    def test_local_history_and_agenda(self):
        self.call('social_import_draft', self.draft())
        history = self.call('social_list_recent_content', {'account_id': '123'})['structuredContent']
        self.assertFalse(history['complete_remote_history'])
        self.assertEqual(len(history['items']), 1)
        agenda = self.call('social_list_agenda', {'start': '2026-11-01T00:00:00-03:00',
                                                'end': '2026-11-10T00:00:00-03:00'})['structuredContent']
        self.assertEqual(agenda['items'], [])
        self.assertFalse(agenda['scheduler']['active'])


if __name__ == '__main__':
    unittest.main()
