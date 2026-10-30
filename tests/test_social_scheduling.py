import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
import tempfile
import time
import sqlite3
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

    def change_data(self, action, **overrides):
        data = {k: v for k, v in self.data.items() if k != 'desired_at'}
        data.update(expected_due_at=self.now + 600, idempotency_key=f'{action}-operation-key-001')
        if action == 'reschedule':
            data['desired_at'] = datetime.fromtimestamp(self.now + 1200, mcp.ZONE).isoformat()
        return data | overrides

    def queue_snapshot(self):
        with app.connect() as c:
            return (dict(c.execute('SELECT * FROM posts WHERE id=?', (self.post_id,)).fetchone()),
                    dict(c.execute('SELECT * FROM post_schedule WHERE post_id=?', (self.post_id,)).fetchone()))

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

    def test_cancel_offline_preserves_art_and_prevents_due_publication(self):
        self.scheduled()
        before, _ = self.queue_snapshot()
        with app.connect() as c:
            c.execute("UPDATE scheduler_runtime SET mode='stopped'")
        result = self.call('social_cancel_schedule', self.change_data('cancel'))
        self.assertFalse(result['isError'], result)
        receipt = result['structuredContent']
        self.assertEqual(receipt['status'], 'cancellation_accepted')
        self.assertTrue(receipt['cancelled_by_operation'])
        self.assertFalse(receipt['scheduled_by_operation'])
        self.assertEqual(self.call('social_get_operation', {'operation_id': receipt['id']})['structuredContent'], receipt)
        post, queue = self.queue_snapshot()
        self.assertEqual((post['publish_status'], post['revision'], queue['state']), ('draft', 1, 'cancelled'))
        self.assertEqual((post['caption'], post['image_name']), (before['caption'], before['image_name']))
        with patch('time.time', return_value=self.now + 600), patch('publishing.publish') as publish:
            self.assertEqual(scheduling.tick(app.connect, app.DB.parent)['status'], 'idle')
            publish.assert_not_called()

    def test_missing_photo_does_not_prevent_status_query_or_cancellation(self):
        self.scheduled()
        post, _ = self.queue_snapshot()
        publishing.image_file(app.DB.parent, post['image_name']).unlink()
        preview = self.call('social_get_draft', {'post_id': self.post_id})['structuredContent']
        self.assertEqual(preview['format'], 'feed_photo')
        self.assertEqual(preview['publish_status'], 'scheduled')
        self.assertFalse(preview['image_available'])
        self.assertIsNone(preview['image_url'])
        self.assertFalse(self.call('social_cancel_schedule', self.change_data('cancel'))['isError'])
        self.assertEqual(self.queue_snapshot()[1]['state'], 'cancelled')

    def test_reschedule_changes_only_time_and_runs_only_at_new_due(self):
        self.scheduled()
        before, _ = self.queue_snapshot()
        result = self.call('social_reschedule_draft', self.change_data('reschedule'))
        self.assertFalse(result['isError'], result)
        receipt = result['structuredContent']
        self.assertEqual(receipt['status'], 'reschedule_accepted')
        self.assertEqual((receipt['previous_due_at'], receipt['due_at']), (self.now + 600, self.now + 1200))
        post, queue = self.queue_snapshot()
        self.assertEqual((post['revision'], queue['revision'], queue['state']), (1, 1, 'queued'))
        self.assertEqual((post['caption'], post['image_name']), (before['caption'], before['image_name']))
        with patch('publishing.publish', return_value={'status': 'published'}) as publish:
            with patch('time.time', return_value=self.now + 600):
                self.assertEqual(scheduling.tick(app.connect, app.DB.parent)['status'], 'idle')
            publish.assert_not_called()
            with patch('time.time', return_value=self.now + 1200):
                self.assertEqual(scheduling.tick(app.connect, app.DB.parent)['status'], 'done')
            self.assertEqual(publish.call_args.args[2]['revision'], 1)

    def test_queue_changes_require_explicit_confirmation_current_revision_and_time(self):
        self.scheduled()
        original = self.queue_snapshot()
        for action, name in [('cancel', 'social_cancel_schedule'), ('reschedule', 'social_reschedule_draft')]:
            for change in [{'confirmed': False}, {'expected_due_at': self.now + 601},
                           {'revision': 1}, {'account_id': '777'}, {'channel': 'Facebook'},
                           {'expected_due_at': True}, {'extra': 'unexpected'}]:
                with self.subTest(action=action, change=change):
                    self.assertTrue(self.call(name, self.change_data(action, **change))['isError'])
                    self.assertEqual(self.queue_snapshot(), original)
            missing = self.change_data(action)
            del missing['confirmed']
            self.assertTrue(self.call(name, missing)['isError'])

    def test_in_progress_or_completed_sends_cannot_be_cancelled_or_rescheduled(self):
        self.scheduled()
        for state, status in [('running', 'sending'), ('processing', 'processing'),
                              ('done', 'published'), ('failed', 'review'), ('cancelled', 'draft')]:
            with app.connect() as c:
                c.execute('UPDATE post_schedule SET state=? WHERE post_id=?', (state, self.post_id))
                c.execute('UPDATE posts SET publish_status=? WHERE id=?', (status, self.post_id))
            before = self.queue_snapshot()
            for action, name in [('cancel', 'social_cancel_schedule'), ('reschedule', 'social_reschedule_draft')]:
                self.assertTrue(self.call(name, self.change_data(action))['isError'])
                self.assertEqual(self.queue_snapshot(), before)

    def test_invalid_reschedule_keeps_the_original_authorized_time(self):
        self.scheduled()
        before = self.queue_snapshot()
        for timestamp in (self.now - 1, self.now + 60, self.now + 91 * 86400, self.now + 600):
            result = self.call('social_reschedule_draft', self.change_data('reschedule',
                desired_at=datetime.fromtimestamp(timestamp, mcp.ZONE).isoformat()))
            self.assertTrue(result['isError'])
            self.assertEqual(self.queue_snapshot(), before)
        for value in ('2026-11-05T09:00:00', '2026-11-05T09:00:00+00:00'):
            self.assertTrue(self.call('social_reschedule_draft', self.change_data('reschedule', desired_at=value))['isError'])
            self.assertEqual(self.queue_snapshot(), before)
        with app.connect() as c:
            c.execute("UPDATE scheduler_runtime SET mode='stopped'")
        self.assertTrue(self.call('social_reschedule_draft', self.change_data('reschedule'))['isError'])
        self.assertEqual(self.queue_snapshot(), before)

    def test_reschedule_conflict_keeps_both_original_schedules(self):
        self.scheduled()
        second = self.import_photo('conflict-original-import-002')
        self.scheduled(self.data | {'post_id': second['post_id'], 'idempotency_key': 'conflict-original-schedule-002',
            'desired_at': datetime.fromtimestamp(self.now + 1200, mcp.ZONE).isoformat()})
        before = self.queue_snapshot()
        self.assertTrue(self.call('social_reschedule_draft', self.change_data('reschedule'))['isError'])
        self.assertEqual(self.queue_snapshot(), before)
        with app.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM post_schedule WHERE state='queued'").fetchone()[0], 2)

    def test_retry_of_cancel_does_not_cancel_a_new_schedule(self):
        self.scheduled()
        data = self.change_data('cancel')
        first = self.call('social_cancel_schedule', data)
        self.assertFalse(first['isError'])
        self.scheduled(self.data | {'revision': 1, 'idempotency_key': 'new-schedule-after-cancel-001',
            'desired_at': datetime.fromtimestamp(self.now + 1200, mcp.ZONE).isoformat()})
        current = self.queue_snapshot()
        self.assertEqual(self.call('social_cancel_schedule', data), first)
        self.assertEqual(self.queue_snapshot(), current)
        self.assertTrue(self.call('social_cancel_schedule', data | {'expected_due_at': self.now + 1200})['isError'])

    def test_retry_of_reschedule_does_not_restore_an_older_time(self):
        self.scheduled()
        first_data = self.change_data('reschedule')
        first = self.call('social_reschedule_draft', first_data)
        self.assertFalse(first['isError'])
        second_data = self.change_data('reschedule', revision=1, expected_due_at=self.now + 1200,
            idempotency_key='second-reschedule-operation-002',
            desired_at=datetime.fromtimestamp(self.now + 1800, mcp.ZONE).isoformat())
        self.assertFalse(self.call('social_reschedule_draft', second_data)['isError'])
        before = self.queue_snapshot()
        self.assertEqual(self.call('social_reschedule_draft', first_data), first)
        self.assertEqual(self.queue_snapshot(), before)
        self.assertEqual(before[1]['due_at'], self.now + 1800)

    def test_change_receipt_failure_rolls_back_cancel_and_reschedule(self):
        receipt = self.scheduled()
        before = self.queue_snapshot()
        for action, name in [('cancel', 'social_cancel_schedule'), ('reschedule', 'social_reschedule_draft')]:
            with patch('social_mcp.secrets.token_hex', return_value=receipt['id']):
                self.assertTrue(self.call(name, self.change_data(action))['isError'])
            self.assertEqual(self.queue_snapshot(), before)
        self.assertTrue(self.call('social_cancel_schedule', self.change_data('cancel',
            idempotency_key=self.data['idempotency_key']))['isError'])
        self.assertTrue(self.call('social_cancel_schedule', self.change_data('cancel',
            idempotency_key='first-import-key-001'))['isError'])

    def test_simultaneous_reschedules_cannot_overwrite_the_winner(self):
        self.scheduled()
        first = self.change_data('reschedule')
        second = self.change_data('reschedule', idempotency_key='competing-reschedule-key-002',
            desired_at=datetime.fromtimestamp(self.now + 1800, mcp.ZONE).isoformat())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda data: self.call('social_reschedule_draft', data), [first, second]))
        self.assertEqual(sum(not result['isError'] for result in results), 1)
        winner = next(r['structuredContent'] for r in results if not r['isError'])
        self.assertEqual(self.queue_snapshot()[1]['due_at'], winner['due_at'])

    def test_cancel_and_due_worker_have_only_one_winner(self):
        self.scheduled()
        def publish(*args, **kwargs):
            with app.connect() as c:
                c.execute("UPDATE posts SET publish_status='published' WHERE id=?", (self.post_id,))
            return {'status': 'published'}
        with patch('time.time', return_value=self.now + 600), patch('publishing.publish', side_effect=publish) as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                cancellation = pool.submit(self.call, 'social_cancel_schedule', self.change_data('cancel'))
                worker = pool.submit(scheduling.tick, app.connect, app.DB.parent, 'http')
                cancelled, outcome = cancellation.result(), worker.result()
            if cancelled['isError']:
                self.assertEqual(outcome['status'], 'done')
                self.assertEqual(send.call_count, 1)
            else:
                self.assertEqual(outcome['status'], 'idle')
                send.assert_not_called()

    def test_migration_preserves_old_schedule_receipts_and_write_annotations(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory = sqlite3.Row
            c.execute('''CREATE TABLE social_mcp_schedule_operations (
                id TEXT PRIMARY KEY,idempotency_key TEXT UNIQUE NOT NULL,content_hash TEXT NOT NULL,
                post_id INTEGER NOT NULL,revision INTEGER NOT NULL,account_id TEXT NOT NULL,
                channel TEXT NOT NULL,desired_at TEXT NOT NULL,due_at INTEGER NOT NULL,created_at INTEGER NOT NULL)''')
            c.execute('INSERT INTO social_mcp_schedule_operations VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('old-operation', 'old-idempotency-key-001', 'old-hash', 1, 0, '123', 'Instagram', self.when, self.now + 600, self.now))
            mcp.initialize(c)
            mcp.initialize(c)
            receipt = mcp.operation(c, 'old-operation')
            self.assertEqual(receipt['status'], 'schedule_accepted')
            self.assertEqual(receipt['due_at'], self.now + 600)
            self.assertIsNone(receipt['previous_due_at'])
        tools = mcp.rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, app.connect, app.DB.parent)['result']['tools']
        for tool in tools:
            if tool['name'] in ('social_cancel_schedule', 'social_reschedule_draft'):
                self.assertFalse(tool['annotations']['readOnlyHint'])
                self.assertTrue(tool['annotations']['destructiveHint'])
