"""Recovery of legacy preview state without recreating approved artwork."""
import hashlib
import io
from unittest.mock import patch
import unittest

from PIL import Image, ImageEnhance

import app
import drive_source as drive
import feed_autonomy as auto
import feed_composer as composer
import product_scene
import tests.test_feed_autonomy as fixtures
from tests.test_feed_autonomy import Client


class RecoveryTests(unittest.TestCase):
    setUp = fixtures.FeedAutonomyTests.setUp
    tearDown = fixtures.FeedAutonomyTests.tearDown
    heartbeat = fixtures.FeedAutonomyTests.heartbeat

    def preview(self):
        self.rules |= {'cadence': 'batch3', 'mode': 'preview'}
        drive.write_private(self.directory / auto.SETTINGS, self.rules)

    def index_models(self):
        files = auto.sync_catalog(app.connect, self.directory, self.client)
        while auto.index_one(app.connect, files, self.client):
            pass
        return files

    def retained_collision(self):
        self.index_models()
        self.preview()
        batch = auto._batch_days(app.connect, self.rules, self.now)
        slot = auto._reserve_batch(app.connect, self.rules, batch, self.now)
        with app.connect() as conn:
            model = conn.execute('SELECT * FROM feed_models WHERE file_id=?',
                                 (slot['file_id'],)).fetchone()
        result = composer.compose(
            app.connect, self.directory,
            {'theme': 'generico', 'file_id': slot['file_id'],
             'request_id': slot['request_id'], 'channel': 'Instagram'},
            self.client, expected_sha256=model['sha256'])
        with app.connect() as conn:
            post = dict(conn.execute('SELECT * FROM posts WHERE id=?',
                                     (result['post_id'],)).fetchone())
            conn.execute("UPDATE feed_auto_slots SET state='retained',post_id=? WHERE slot=?",
                         (post['id'], slot['slot']))
            conn.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(?,3,?,'cancelled')",
                         (post['id'], self.now - 3600))
            conn.execute('''INSERT INTO social_mcp_schedule_operations
                (id,idempotency_key,content_hash,post_id,revision,account_id,channel,
                 desired_at,due_at,created_at,action)
                VALUES(?,?,?,?,3,?,'Instagram',?,?,?,'cancel')''',
                         ('e'*32, 'legacy-cancel-operation-123', 'f'*64,
                          post['id'], self.rules['account_id'], '2026-11-05T08:00:00',
                          self.now - 3600, self.now - 4000))
        return slot, post

    def collision_snapshot(self, post_id, slot):
        with app.connect() as conn:
            return {
                'post': dict(conn.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()),
                'schedule': dict(conn.execute('SELECT * FROM post_schedule WHERE post_id=?', (post_id,)).fetchone()),
                'slot': dict(conn.execute('SELECT * FROM feed_auto_slots WHERE slot=?', (slot['slot'],)).fetchone()),
                'composition': dict(conn.execute('SELECT * FROM feed_compositions WHERE request_id=?',
                                                (slot['request_id'],)).fetchone()),
                'receipt': dict(conn.execute('SELECT * FROM social_mcp_schedule_operations').fetchone()),
            }

    def test_retained_id_collision_preserves_art_and_historical_cancel_receipt(self):
        slot, post = self.retained_collision()
        before = self.collision_snapshot(post['id'], slot)
        original_bytes = (self.directory / 'media' / post['image_name']).read_bytes()
        self.assertEqual(auto.recover_retained_preview(app.connect, self.rules), 1)
        self.assertEqual(auto.recover_retained_preview(app.connect, self.rules), 0)
        with app.connect() as conn:
            current_slot = conn.execute('SELECT * FROM feed_auto_slots WHERE slot=?',
                                        (slot['slot'],)).fetchone()
            self.assertNotEqual(current_slot['post_id'], post['id'])
            self.assertEqual(current_slot['state'], 'reserved')
            current = conn.execute('SELECT * FROM posts WHERE id=?',
                                   (current_slot['post_id'],)).fetchone()
            self.assertEqual(current['caption'], post['caption'])
            self.assertEqual(current['image_name'], post['image_name'])
            self.assertEqual(current['revision'], 0)
            self.assertEqual(current['publish_status'], 'draft')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 1)
            self.assertIsNone(conn.execute('SELECT * FROM posts WHERE id=?', (post['id'],)).fetchone())
            self.assertEqual(dict(conn.execute('SELECT * FROM post_schedule WHERE post_id=?',
                                              (post['id'],)).fetchone()), before['schedule'])
            self.assertEqual(dict(conn.execute('SELECT * FROM social_mcp_schedule_operations').fetchone()),
                             before['receipt'])
            self.assertEqual(conn.execute('SELECT post_id FROM feed_compositions WHERE request_id=?',
                                          (slot['request_id'],)).fetchone()[0], current['id'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_repairs').fetchone()[0], 1)
        self.assertEqual((self.directory / 'media' / post['image_name']).read_bytes(), original_bytes)
        with patch('publishing.publish', side_effect=AssertionError('preview must not publish')):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['drafts'], 1)
            self.assertEqual(progress['blocked_slots'], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM post_schedule WHERE state='queued'").fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 1)

    def assert_collision_untouched(self, change, parameters=()):
        slot, post = self.retained_collision()
        with app.connect() as conn:
            conn.execute(change, parameters + (post['id'],))
        before = self.collision_snapshot(post['id'], slot)
        self.assertEqual(auto.recover_retained_preview(app.connect, self.rules), 0)
        self.assertEqual(self.collision_snapshot(post['id'], slot), before)

    def test_edited_retained_art_is_not_reassigned(self):
        self.assert_collision_untouched(
            "UPDATE posts SET revision=1,caption='Legenda alterada pelo proprietário' WHERE id=?")

    def test_manual_source_is_not_reassigned(self):
        self.assert_collision_untouched("UPDATE posts SET source='Manual' WHERE id=?")

    def test_live_schedule_is_not_detached(self):
        self.assert_collision_untouched("UPDATE post_schedule SET state='queued' WHERE post_id=?")

    def test_actual_cancelled_preview_is_not_reactivated(self):
        self.assert_collision_untouched(
            "UPDATE posts SET revision=4,source='Prévia de lote · revisar',account_id=? WHERE id=?",
            (self.rules['account_id'],))

    def test_old_cancelled_schedule_at_revision_zero_is_still_repaired(self):
        slot, post = self.retained_collision()
        with app.connect() as conn:
            conn.execute('UPDATE post_schedule SET revision=0 WHERE post_id=?', (post['id'],))
        self.assertEqual(auto.recover_retained_preview(app.connect, self.rules), 1)
        with app.connect() as conn:
            current = conn.execute('SELECT * FROM feed_auto_slots WHERE slot=?', (slot['slot'],)).fetchone()
            self.assertEqual(current['state'], 'reserved')
            self.assertNotEqual(current['post_id'], post['id'])
            self.assertEqual(conn.execute('SELECT state FROM post_schedule WHERE post_id=?',
                                          (post['id'],)).fetchone()[0], 'cancelled')

    def test_newer_schedule_is_not_detached(self):
        self.assert_collision_untouched('UPDATE post_schedule SET due_at=? WHERE post_id=?',
                                        (self.now + 3600,))

    def test_recovery_is_not_enabled_for_publish_mode(self):
        slot, post = self.retained_collision()
        before = self.collision_snapshot(post['id'], slot)
        self.assertEqual(auto.recover_retained_preview(app.connect, self.rules | {'mode': 'publish'}), 0)
        self.assertEqual(self.collision_snapshot(post['id'], slot), before)

    def legacy_review(self, *, all_models=False):
        files = self.index_models()
        self.preview()
        with app.connect() as conn:
            selected = conn.execute('SELECT file_id FROM feed_models ORDER BY file_id LIMIT 1').fetchone()[0]
            where = '' if all_models else ' WHERE file_id=?'
            conn.execute("UPDATE feed_models SET state='review',review_reason='',cutout_version=''" + where,
                         () if all_models else (selected,))
        self.client.downloads = 0
        self.client.requested_ids.clear()
        return files, selected

    def test_recheck_checks_only_one_unused_review_candidate(self):
        files, _ = self.legacy_review(all_models=True)
        with app.connect() as conn:
            before = {r['file_id']: dict(r) for r in conn.execute('SELECT * FROM feed_models')}
        auto.recheck_one_review(app.connect, files, self.client)
        self.assertEqual(self.client.downloads, 1)
        with app.connect() as conn:
            after = {r['file_id']: dict(r) for r in conn.execute('SELECT * FROM feed_models')}
        self.assertEqual(sum(before[key] != after[key] for key in before), 1)
        self.assertEqual(sum(row['state'] == 'ready' for row in after.values()), 1)
        self.assertEqual(sum(row['state'] == 'review' for row in after.values()), 3)

    def test_failed_cutout_is_checked_only_once_per_detector_version(self):
        files, selected = self.legacy_review()
        with patch('product_scene.detect_quad', side_effect=product_scene.CutoutError('paper partially hidden')) as detect:
            auto.recheck_one_review(app.connect, files, self.client)
            auto.recheck_one_review(app.connect, files, self.client)
        self.assertEqual(self.client.downloads, 1)
        self.assertEqual(detect.call_count, 1)
        with app.connect() as conn:
            model = conn.execute('SELECT * FROM feed_models WHERE file_id=?', (selected,)).fetchone()
            self.assertEqual(model['state'], 'review')
            self.assertEqual(model['cutout_version'], product_scene.CUTOUT_VERSION)
            self.assertTrue(model['review_reason'])

    def test_changed_original_is_pending_instead_of_released(self):
        files, selected = self.legacy_review()
        self.client.data[selected] += b'changed-source'
        auto.recheck_one_review(app.connect, files, self.client)
        with app.connect() as conn:
            model = conn.execute('SELECT * FROM feed_models WHERE file_id=?', (selected,)).fetchone()
            self.assertEqual(model['state'], 'pending')
            self.assertNotEqual(model['sha256'], hashlib.sha256(self.client.data[selected]).hexdigest())
        self.assertEqual(self.client.downloads, 1)

    def test_already_used_model_is_not_rechecked(self):
        files = self.index_models()
        self.preview()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            used = conn.execute('SELECT file_id FROM feed_auto_slots').fetchone()[0]
            conn.execute("UPDATE feed_models SET state='review',review_reason='',cutout_version=''")
        self.client.downloads = 0
        self.client.requested_ids.clear()
        auto.recheck_one_review(app.connect, files, self.client)
        self.assertNotIn(used, self.client.requested_ids)
        self.assertEqual(self.client.downloads, 1)

    def test_similar_models_stay_protected_during_recheck(self):
        original = 'original_model_0000'
        variant = 'possible_same_model_photo'
        with Image.open(io.BytesIO(self.client.data[original])) as image:
            output = io.BytesIO()
            ImageEnhance.Brightness(image).enhance(1.01).save(output, format='PNG')
        self.client.data[variant] = output.getvalue()
        files = self.index_models()
        self.preview()
        with app.connect() as conn:
            conn.execute("UPDATE feed_models SET state='review',review_reason='',cutout_version='' WHERE file_id IN (?,?)",
                         (original, variant))
        self.client.downloads = 0
        with patch('product_scene.detect_quad', side_effect=AssertionError('possible duplicate must remain held')):
            auto.recheck_one_review(app.connect, files, self.client)
        with app.connect() as conn:
            states = [r['state'] for r in conn.execute('SELECT state FROM feed_models WHERE file_id IN (?,?)',
                                                     (original, variant))]
            self.assertEqual(states, ['review', 'review'])

    def test_rechecking_completes_same_batch_without_recreating_first_draft(self):
        self.client = Client(10)
        self.index_models()
        self.preview()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            first = dict(conn.execute('SELECT * FROM posts').fetchone())
            batch = conn.execute('SELECT id FROM feed_batches').fetchone()[0]
            used = conn.execute('SELECT file_id FROM feed_auto_slots').fetchone()[0]
            conn.execute("UPDATE feed_models SET state='review',review_reason='',cutout_version='' WHERE file_id!=?", (used,))
        original_bytes = (self.directory / 'media' / first['image_name']).read_bytes()
        self.client.requested_ids.clear()
        with patch('publishing.publish', side_effect=AssertionError('preview must not publish')):
            for _ in range(6):
                auto.tick(app.connect, self.directory, self.client)
                with app.connect() as conn:
                    if auto.batch_progress(conn, self.rules)['drafts'] == 3:
                        break
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['id'], batch)
            self.assertEqual(progress['drafts'], 3)
            self.assertEqual(progress['prepared'], 3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            self.assertEqual(dict(conn.execute('SELECT * FROM posts WHERE id=?', (first['id'],)).fetchone()), first)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM feed_models WHERE state='review'").fetchone()[0], 7)
        self.assertEqual(len(self.client.requested_ids), 2)
        self.assertEqual((self.directory / 'media' / first['image_name']).read_bytes(), original_bytes)


if __name__ == '__main__':
    unittest.main()
