import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import app
import meta
import publishing
import scheduling
import social_mcp as mcp
from test_publishing import jpeg


class SocialSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'test.db'
        app.initialize()
        self.env = patch.dict(os.environ, {'ARTENOALTAR_ORIGIN': 'https://gestao.example'})
        self.env.start()
        self.cache = patch('meta.status', return_value={'accounts': [
            {'id': '123', 'channel': 'Instagram', 'name': '@arte.no.altar', 'access_token': 'NEVER_RETURN'},
            {'id': '777', 'channel': 'Facebook', 'name': 'Arte no Altar'}]})
        self.cache.start()
        self.now = int(time.time())
        self.clock = patch('time.time', return_value=self.now)
        self.clock.start()
        with app.connect() as c:
            c.execute("INSERT INTO scheduler_runtime VALUES(1,?,'http')", (self.now,))
        self.imported = self.import_photo('first-import-key-001')
        self.post_id = self.imported['post_id']
        self.when = datetime.fromtimestamp(self.now + 600, mcp.ZONE).isoformat()
        self.data = {'post_id': self.post_id, 'revision': 0, 'account_id': '123',
                     'channel': 'Instagram', 'desired_at': self.when,
                     'confirmed': True, 'idempotency_key': 'first-schedule-key-001'}

    def tearDown(self):
        self.clock.stop()
        self.cache.stop()
        self.env.stop()
        app.DB = self.old_db
        self.temp.cleanup()

    def call(self, name, data):
        return mcp.rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                        'params': {'name': name, 'arguments': data}}, app.connect, app.DB.parent)['result']

    def import_photo(self, key, account='123', channel='Instagram'):
        result = self.call('social_import_draft', {'account_id': account, 'channel': channel,
            'format': 'feed_photo', 'caption': 'Arte aprovada', 'confirmed': True,
            'image_base64': base64.b64encode(jpeg()).decode(), 'idempotency_key': key})
        self.assertFalse(result['isError'], result)
        return result['structuredContent']

    def scheduled(self, data=None):
        result = self.call('social_schedule_draft', self.data if data is None else data)
        self.assertFalse(result['isError'], result)
        return result['structuredContent']

    def test_preview_is_scoped_and_contains_exact_review(self):
        result = self.call('social_get_draft', {'post_id': self.post_id})
        self.assertFalse(result['isError'])
        preview = result['structuredContent']
        self.assertEqual((preview['revision'], preview['account_id'], preview['channel']), (0, '123', 'Instagram'))
        self.assertEqual(preview['caption'], 'Arte aprovada')
        self.assertEqual(preview['format'], 'feed_photo')
        self.assertTrue(preview['image_url'].startswith('https://gestao.example/media/'))
        self.assertTrue(preview['scheduler']['active'])
        self.assertNotIn('NEVER_RETURN', str(result))
        self.assertNotIn('image_name', preview)
        with app.connect() as c:
            c.execute("UPDATE posts SET account_id='999' WHERE id=?", (self.post_id,))
        self.assertTrue(self.call('social_get_draft', {'post_id': self.post_id})['isError'])
        self.assertTrue(self.call('social_get_draft', {'post_id': 999})['isError'])

    def test_confirmed_schedule_receipt_and_agenda_without_immediate_publication(self):
        with patch('publishing.publish', side_effect=AssertionError('must not publish now')):
            receipt = self.scheduled()
            self.assertEqual(receipt['status'], 'schedule_accepted')
            self.assertTrue(receipt['scheduled_by_operation'])
            self.assertFalse(receipt['published_by_operation'])
            self.assertEqual(receipt['due_at'], self.now + 600)
            self.assertEqual(self.call('social_get_operation', {'operation_id': receipt['id']})['structuredContent'], receipt)
            self.assertEqual(self.call('social_get_operation', {'operation_id': self.imported['id']})['structuredContent'], self.imported)
            preview = self.call('social_get_draft', {'post_id': self.post_id})['structuredContent']
            self.assertEqual(preview['publish_status'], 'scheduled')
            self.assertEqual(preview['schedule'], {'due_at': self.now + 600, 'state': 'queued'})
            agenda = self.call('social_list_agenda', {
                'start': datetime.fromtimestamp(self.now, mcp.ZONE).isoformat(),
                'end': datetime.fromtimestamp(self.now + 86400, mcp.ZONE).isoformat()})['structuredContent']
            self.assertEqual([p['id'] for p in agenda['items']], [self.post_id])
        tools = mcp.rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, app.connect, app.DB.parent)['result']['tools']
        annotations = {t['name']: t['annotations']['readOnlyHint'] for t in tools}
        self.assertFalse(annotations['social_schedule_draft'])
        self.assertTrue(annotations['social_get_draft'])

    def test_confirmation_dates_arguments_and_heartbeat_fail_closed(self):
        invalid = [{'confirmed': False}, {'revision': True}, {'post_id': True},
                   {'desired_at': '2026-11-05T09:00:00'},
                   {'desired_at': datetime.fromtimestamp(self.now + 600, mcp.ZONE).isoformat().replace('-03:00', '+00:00')},
                   {'desired_at': datetime.fromtimestamp(self.now - 1, mcp.ZONE).isoformat()},
                   {'desired_at': datetime.fromtimestamp(self.now + 91 * 86400, mcp.ZONE).isoformat()},
                   {'desired_at': datetime.fromtimestamp(self.now + 60, mcp.ZONE).isoformat()},
                   {'unexpected': 'financial-data'}]
        with patch('publishing.publish') as publish:
            for change in invalid:
                with self.subTest(change=change):
                    self.assertTrue(self.call('social_schedule_draft', self.data | change)['isError'])
            missing = {k: v for k, v in self.data.items() if k != 'confirmed'}
            self.assertTrue(self.call('social_schedule_draft', missing)['isError'])
            for mode, tick in [('stopped', self.now), ('http', self.now - 151)]:
                with app.connect() as c:
                    c.execute('UPDATE scheduler_runtime SET mode=?,last_tick=?', (mode, tick))
                self.assertTrue(self.call('social_schedule_draft', self.data)['isError'])
            publish.assert_not_called()
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM social_mcp_schedule_operations').fetchone()[0], 0)

    def test_changed_revision_destination_or_missing_photo_cannot_schedule(self):
        with app.connect() as c:
            c.execute("UPDATE posts SET revision=1,caption='Alterada' WHERE id=?", (self.post_id,))
        self.assertTrue(self.call('social_schedule_draft', self.data)['isError'])
        for change in [{'account_id': '777'}, {'channel': 'Facebook'}]:
            self.assertTrue(self.call('social_schedule_draft', self.data | {'revision': 1} | change)['isError'])
        with app.connect() as c:
            c.execute("UPDATE posts SET image_name='' WHERE id=?", (self.post_id,))
        self.assertTrue(self.call('social_schedule_draft', self.data | {'revision': 1})['isError'])

    def test_retry_after_cancellation_or_executor_off_does_not_reschedule(self):
        receipt = self.scheduled()
        with app.connect() as c:
            scheduling.cancel(c, {'id': self.post_id})
            c.execute("UPDATE scheduler_runtime SET mode='stopped'")
        with patch('time.time', return_value=self.now + 1000):
            self.assertEqual(self.scheduled(), receipt)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT state FROM post_schedule').fetchone()[0], 'cancelled')
            self.assertEqual(c.execute('SELECT publish_status FROM posts').fetchone()[0], 'draft')
        changed = self.data | {'desired_at': datetime.fromtimestamp(self.now + 1200, mcp.ZONE).isoformat()}
        self.assertTrue(self.call('social_schedule_draft', changed)['isError'])

    def test_import_and_schedule_cannot_reuse_each_others_operation_keys(self):
        self.assertTrue(self.call('social_schedule_draft', self.data | {'idempotency_key': 'first-import-key-001'})['isError'])
        self.scheduled()
        result = self.call('social_import_draft', {'account_id': '123', 'channel': 'Instagram',
            'format': 'feed_photo', 'caption': 'Outra arte', 'confirmed': True,
            'image_base64': base64.b64encode(jpeg()).decode(), 'idempotency_key': self.data['idempotency_key']})
        self.assertTrue(result['isError'])

    def test_same_account_minute_conflicts_but_different_channel_can_share_time(self):
        self.scheduled()
        another = self.import_photo('second-import-key-002')
        data = self.data | {'post_id': another['post_id'], 'idempotency_key': 'second-schedule-key-002'}
        # Mesmo minuto, mesmo que os segundos sejam diferentes.
        other_second = self.now + 600 + (1 if (self.now + 600) % 60 != 59 else -1)
        data['desired_at'] = datetime.fromtimestamp(other_second, mcp.ZONE).isoformat()
        self.assertTrue(self.call('social_schedule_draft', data)['isError'])
        facebook = self.import_photo('facebook-import-key-003', '777', 'Facebook')
        self.scheduled(self.data | {'post_id': facebook['post_id'], 'account_id': '777',
                       'channel': 'Facebook', 'idempotency_key': 'facebook-schedule-key-003'})

    def test_receipt_failure_rolls_back_the_queue(self):
        first = self.scheduled()
        another = self.import_photo('rollback-import-key-002')
        data = self.data | {'post_id': another['post_id'], 'idempotency_key': 'rollback-schedule-key-002',
            'desired_at': datetime.fromtimestamp(self.now + 1200, mcp.ZONE).isoformat()}
        with patch('social_mcp.secrets.token_hex', return_value=first['id']):
            self.assertTrue(self.call('social_schedule_draft', data)['isError'])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT publish_status FROM posts WHERE id=?', (another['post_id'],)).fetchone()[0], 'draft')
            self.assertIsNone(c.execute('SELECT * FROM post_schedule WHERE post_id=?', (another['post_id'],)).fetchone())

    def test_concurrent_retries_or_competing_posts_do_not_duplicate_queue(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call('social_schedule_draft', self.data), range(2)))
        self.assertTrue(all(not r['isError'] for r in results), results)
        self.assertEqual(results[0], results[1])
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM social_mcp_schedule_operations').fetchone()[0], 1)
            scheduling.cancel(c, {'id': self.post_id})
        second = self.import_photo('concurrent-import-key-002')
        first_data = self.data | {'revision': 1, 'idempotency_key': 'concurrent-schedule-key-001'}
        second_data = self.data | {'post_id': second['post_id'], 'idempotency_key': 'concurrent-schedule-key-002'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda data: self.call('social_schedule_draft', data), [first_data, second_data]))
        self.assertEqual(sum(not r['isError'] for r in results), 1)

    def test_mcp_schedule_is_consumed_by_instagram_worker_with_fake_meta(self):
        self.scheduled()
        meta.write_private(app.DB.parent/'meta-config.json', {'app_id': '123', 'config_id': '456', 'app_secret': 'test-secret'})
        meta.write_private(app.DB.parent/'meta-connection.json', {'app_id': '123', 'access_token': 'test-token'})
        reads = [
            {'data': [{'id': '777', 'access_token': 'page-token', 'instagram_business_account': {'id': '123'}}]},
            {'images': [{'source': 'https://scontent.example.fbcdn.net/art.jpg'}]},
            {'status_code': 'FINISHED'}]
        with patch('meta.verify_accounts', return_value={'accounts': [{'id': '123', 'channel': 'Instagram', 'publishing_scope_granted': True}]}), patch('meta.graph_read', side_effect=reads), patch('publishing.graph_post', side_effect=[{'id': '111'}, {'id': '222'}, {'id': '333'}]) as send:
            with patch('time.time', return_value=self.now + 599):
                self.assertEqual(scheduling.tick(app.connect, app.DB.parent, 'http')['status'], 'idle')
            send.assert_not_called()
            with patch('time.time', return_value=self.now + 600):
                self.assertEqual(scheduling.tick(app.connect, app.DB.parent, 'http')['status'], 'processing')
            with patch('time.time', return_value=self.now + 660):
                self.assertEqual(scheduling.tick(app.connect, app.DB.parent, 'http')['status'], 'done')
                self.assertEqual(scheduling.tick(app.connect, app.DB.parent, 'http')['status'], 'idle')
            self.assertEqual([c.args[1] for c in send.call_args_list], ['777/photos', '123/media', '123/media_publish'])
        preview = self.call('social_get_draft', {'post_id': self.post_id})['structuredContent']
        self.assertEqual((preview['publish_status'], preview['remote_id']), ('published', '333'))
