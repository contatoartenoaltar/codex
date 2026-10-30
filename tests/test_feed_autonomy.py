from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from PIL import Image, ImageEnhance
import app
import drive_source as drive
import feed_autonomy as auto
import scheduling


class Client:
    def __init__(self, count=4):
        self.data = {}
        for index in range(count):
            image = Image.frombytes('RGB', (320, 240), random.Random(index).randbytes(320*240*3))
            output = io.BytesIO()
            image.save(output, format='PNG')
            self.data[f'original_model_{index:04d}'] = output.getvalue()
        self.downloads = 0
        self.requested_ids = set()

    def catalog(self, folder):
        return {'folder_id': folder, 'checked_at': '2026-11-05', 'complete': True,
                'files': [{'id': key, 'name': 'Modelo cliente.png', 'mimeType': 'image/png',
                           'size': str(len(value)), 'md5Checksum': hashlib.md5(value).hexdigest()}
                          for key, value in self.data.items()]}

    def download_image(self, item):
        self.downloads += 1
        self.requested_ids.add(item['id'])
        return self.data[item['id']]


class FeedAutonomyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        self.directory = Path(self.tmp.name)
        app.DB = self.directory/'test.db'
        app.initialize()
        self.now = int(datetime(2026, 11, 5, 9, tzinfo=scheduling.ZONE).timestamp())
        self.clock = patch('time.time', side_effect=lambda: self.now)
        self.clock.start()
        self.accounts = [{'id': '123456', 'channel': 'Instagram', 'name': 'arte.no.altar',
                          'publishing_scope_granted': True}]
        self.account_patch = patch('meta.status', return_value={'accounts': self.accounts})
        self.account_patch.start()
        # Fixtures de fluxo usam ruído sem papel. A geometria é testada separadamente.
        self.cutout_patch = patch('product_scene.detect_quad', return_value=[[10, 10], [309, 10], [309, 229], [10, 229]])
        self.cutout_patch.start()
        self.client = Client()
        drive.write_private(self.directory/drive.CONFIG_FILE, {'folder_id': 'original_folder_123'})
        self.rules = {'enabled': True, 'id': 'a'*32, 'username': auto.ACCOUNT, 'account_id': '123456',
                      'channel': 'Instagram', 'rules_hash': auto.rules_hash(), 'timezone': 'America/Sao_Paulo',
                      'time': '12:00', 'days_ahead': 3}
        drive.write_private(self.directory/auto.SETTINGS, self.rules)
        self.heartbeat()

    def tearDown(self):
        self.cutout_patch.stop()
        self.account_patch.stop()
        self.clock.stop()
        app.DB = self.old_db
        self.tmp.cleanup()

    def heartbeat(self):
        with app.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO scheduler_runtime VALUES(1,?,'http')", (self.now,))

    def tick(self, recognizer=lambda raw: 'ofertas'):
        return auto.tick(app.connect, self.directory, self.client, recognizer)

    def index_all(self, recognizer=lambda raw: 'ofertas'):
        for _ in self.client.data:
            self.assertEqual(self.tick(recognizer), 'indexing')

    def test_ocr_uses_large_confident_title_and_refuses_ambiguous_topics(self):
        word = lambda text, height, conf=95: {'text': text, 'height': str(height), 'conf': str(conf)}
        self.assertEqual(auto.detect_theme([word('OFERTA', 50), word('dízimos', 12)], 1080), 'ofertas')
        self.assertEqual(auto.detect_theme([word('Primícias', 75), word('oferta', 30)], 1080), 'primicias')
        self.assertEqual(auto.detect_theme([word('CEIA', 70)], 1080), 'santa_ceia')
        self.assertEqual(auto.detect_theme([word('Dízimo', 60), word('oferta', 55)], 1080), '')
        self.assertEqual(auto.detect_theme([word('dízimos', 12)], 1080), '')
        self.assertEqual(auto.detect_theme([word('Dízimo', 60, 30)], 1080), '')

    def test_three_days_queue_and_model_cycle_survive_restart_without_repeats(self):
        # Mesmo original em outro ID não ganha nova chance no sorteio.
        self.client.data['duplicate_photo_123'] = self.client.data['original_model_0000']
        self.index_all()
        for _ in range(3):
            self.assertEqual(self.tick(), 'prepared')
            app.initialize()
        self.assertEqual(self.tick(), 'waiting')
        with app.connect() as conn:
            rows = conn.execute('SELECT * FROM feed_auto_slots ORDER BY rowid').fetchall()
            self.assertEqual(len({r['model_key'] for r in rows}), 3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 3)
            for row in rows:
                self.assertEqual(row['state'], 'queued')
                self.assertEqual(datetime.fromtimestamp(row['due_at'], scheduling.ZONE).hour, 12)
                post = conn.execute('SELECT * FROM posts WHERE id=?', (row['post_id'],)).fetchone()
                self.assertEqual(post['account_id'], '123456')
                self.assertEqual(post['publish_status'], 'scheduled')
        for _ in range(2):
            self.now += 86400
            self.heartbeat()
            self.assertEqual(self.tick(), 'prepared')
        with app.connect() as conn:
            rows = conn.execute('SELECT * FROM feed_auto_slots ORDER BY rowid').fetchall()
            self.assertEqual(len({r['model_key'] for r in rows[:4]}), 4)
            self.assertEqual([r['cycle'] for r in rows], [1, 1, 1, 1, 2])
            self.assertNotEqual(rows[-1]['model_key'], rows[-2]['model_key'])

    def test_uncertain_model_prevents_cycle_restart_and_duplicate_reservation(self):
        uncertain = self.client.data['original_model_0003']
        self.index_all(lambda raw: '' if raw == uncertain else 'ofertas')
        for _ in range(3):
            self.assertEqual(self.tick(), 'prepared')
        self.now += 86400
        self.heartbeat()
        self.assertEqual(self.tick(), 'waiting')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_auto_slots').fetchone()[0], 3)
            self.assertEqual(auto.status(conn, self.directory)['models']['review'], 1)

    def test_interruption_after_composition_reuses_same_draft_and_cancel_is_respected(self):
        self.index_all()
        with patch('scheduling.save_automatic', side_effect=OSError('temporary interruption')):
            with self.assertRaises(OSError):
                self.tick()
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 1)
        self.assertEqual(self.tick(), 'prepared')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 1)
            row = conn.execute('SELECT * FROM post_schedule').fetchone()
            scheduling.cancel(conn, {'id': row['post_id'], 'revision': row['revision'], 'expected_due_at': row['due_at']})
        # Próxima execução cuida de outro dia; não reativa o cancelado.
        self.assertEqual(self.tick(), 'prepared')
        with app.connect() as conn:
            cancelled = conn.execute('SELECT * FROM post_schedule WHERE post_id=?', (row['post_id'],)).fetchone()
            self.assertEqual(cancelled['state'], 'cancelled')

    def test_disabled_wrong_account_and_changed_rules_never_create(self):
        drive.write_private(self.directory/auto.SETTINGS, self.rules | {'enabled': False})
        self.assertEqual(self.tick(), 'disabled')
        self.assertEqual(self.client.downloads, 0)
        drive.write_private(self.directory/auto.SETTINGS, self.rules)
        self.accounts[0]['id'] = '999'
        with self.assertRaises(ValueError):
            self.tick()
        self.accounts[0]['id'] = '123456'
        drive.write_private(self.directory/auto.SETTINGS, self.rules | {'rules_hash': 'changed'})
        with self.assertRaises(ValueError):
            self.tick()
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 0)

    def test_visual_rejection_pauses_only_generated_queue_and_blocks_reactivation(self):
        self.index_all()
        self.assertEqual(self.tick(), 'prepared')
        with app.connect() as conn:
            manual = conn.execute("INSERT INTO posts(product,channel,caption,source,account_id,publish_status) VALUES('Manual','Instagram','Legenda','Manual','123456','scheduled')").lastrowid
            conn.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(?,0,?,'queued')", (manual, self.now+600))
        result = auto.pause_for_layout_review(app.connect, self.directory)
        self.assertEqual(result, {'cancelled': 1, 'in_flight': 0})
        self.assertEqual(self.tick(), 'disabled')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT state FROM post_schedule WHERE post_id=?', (manual,)).fetchone()[0], 'queued')
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM post_schedule WHERE state='cancelled'").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            auto.enable(self.directory)

    def test_enable_verifies_exact_account_and_keeps_policy_identity(self):
        with patch('feed_autonomy.engine'), patch('meta.verify_accounts', return_value={'accounts': self.accounts}):
            enabled = auto.enable(self.directory)
            self.assertEqual(enabled['id'], self.rules['id'])
            self.assertEqual(enabled['account_id'], '123456')
            self.assertEqual((self.directory/auto.SETTINGS).stat().st_mode & 0o777, 0o600)
            self.accounts[0]['name'] = 'other.account'
            with self.assertRaises(ValueError):
                auto.enable(self.directory)

    def test_manual_edit_after_interruption_is_retained_without_automatic_publication(self):
        self.index_all()
        with patch('scheduling.save_automatic', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.tick()
        with app.connect() as conn:
            conn.execute("UPDATE posts SET caption='Alteração manual',revision=1")
        self.assertEqual(self.tick(), 'retained')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT state FROM feed_auto_slots').fetchone()[0], 'retained')
            self.assertEqual(conn.execute('SELECT caption FROM posts').fetchone()[0], 'Alteração manual')

    def test_existing_noon_schedule_is_preserved_and_new_feed_uses_1215(self):
        self.index_all()
        noon = int(datetime(2026, 11, 5, 12, tzinfo=scheduling.ZONE).timestamp())
        with app.connect() as conn:
            post = conn.execute("INSERT INTO posts(product,channel,caption,source,account_id,publish_status) VALUES('Existente','Instagram','Legenda','Manual','123456','scheduled')").lastrowid
            conn.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(?,0,?,'queued')", (post, noon))
        self.assertEqual(self.tick(), 'prepared')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT due_at FROM feed_auto_slots').fetchone()[0], noon+900)
            self.assertEqual(conn.execute('SELECT due_at FROM post_schedule WHERE post_id=?', (post,)).fetchone()[0], noon)

    def test_policy_cannot_schedule_an_unrelated_draft_or_changed_original(self):
        with app.connect() as conn:
            post = conn.execute("INSERT INTO posts(product,channel,caption,source,account_id) VALUES('Manual','Instagram','Legenda','Manual','123456')").lastrowid
            with self.assertRaises(ValueError):
                scheduling.save_automatic(conn, self.directory, post_id=post, revision=0,
                                          due_at=self.now+3600, policy_id=self.rules['id'])
        self.index_all()
        real = self.client.download_image
        def changed(item):
            original = real(item)
            return original + b'changed'
        self.client.download_image = changed
        with self.assertRaises(auto.composer.SourceChanged):
            self.tick()
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM feed_models WHERE state='pending'").fetchone()[0], 1)

    def test_parallel_trigger_is_busy_without_download_or_new_selection(self):
        real = self.client.download_image
        def during_download(item):
            self.assertEqual(self.tick(), 'busy')
            return real(item)
        self.client.download_image = during_download
        self.assertEqual(self.tick(), 'indexing')
        self.assertEqual(self.client.downloads, 1)

    def test_batches_prepare_only_three_candidates_and_wait_until_last_day(self):
        self.client = Client(10)
        self.rules |= {'cadence': 'batch3', 'mode': 'publish'}
        drive.write_private(self.directory/auto.SETTINGS, self.rules)
        for _ in range(3):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        self.assertEqual(len(self.client.requested_ids), 3)
        with app.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM feed_models WHERE state='pending'").fetchone()[0], 7)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_batches').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 3)
        self.now += 86400
        self.heartbeat()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'waiting')
        self.assertEqual(len(self.client.requested_ids), 3)
        self.now += 86400
        self.heartbeat()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_batches').fetchone()[0], 2)
            slots = conn.execute('SELECT * FROM feed_auto_slots ORDER BY rowid').fetchall()
            self.assertEqual(len({r['model_key'] for r in slots}), 4)
            last_date = datetime.fromtimestamp(slots[-1]['due_at'], scheduling.ZONE).date()
            self.assertEqual(last_date.isoformat(), '2026-11-08')

    def test_preview_batch_never_schedules_and_activation_queues_same_reviewed_images(self):
        self.rules |= {'cadence': 'batch3', 'mode': 'preview'}
        drive.write_private(self.directory/auto.SETTINGS, self.rules)
        for _ in range(3):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'waiting')
        with app.connect() as conn:
            originals = [dict(r) for r in conn.execute('SELECT * FROM posts ORDER BY id')]
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
        self.rules['mode'] = 'publish'
        drive.write_private(self.directory/auto.SETTINGS, self.rules)
        for _ in range(3):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            queued = [dict(r) for r in conn.execute('SELECT * FROM posts ORDER BY id')]
            self.assertEqual(len(queued), 3)
            self.assertEqual([p['image_name'] for p in queued], [p['image_name'] for p in originals])
            self.assertEqual([p['caption'] for p in queued], [p['caption'] for p in originals])
            self.assertTrue(all(p['publish_status'] == 'scheduled' for p in queued))

    def test_failed_cutout_tries_another_model_for_the_same_batch_day(self):
        import product_scene
        self.rules |= {'cadence': 'batch3', 'mode': 'preview'}
        drive.write_private(self.directory/auto.SETTINGS, self.rules)
        with patch('product_scene.detect_quad', side_effect=product_scene.CutoutError('incomplete paper')):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'cutout_review')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_auto_slots').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 0)
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            row = conn.execute('SELECT * FROM feed_auto_slots').fetchone()
            self.assertEqual(datetime.fromtimestamp(row['due_at'], scheduling.ZONE).date().isoformat(), '2026-11-05')
            self.assertEqual(row['state'], 'draft')

    def preview_rules(self):
        self.rules |= {'cadence': 'batch3', 'mode': 'preview', 'batch_review_required': True}
        drive.write_private(self.directory/auto.SETTINGS, self.rules)

    def reserved_preview_batch(self, states=('reserved', 'reserved', 'reserved')):
        self.index_all(lambda raw: 'generico')
        self.preview_rules()
        batch = auto._batch_days(app.connect, self.rules, self.now)
        first = datetime.fromisoformat(batch['first_day']).date()
        with app.connect() as conn:
            models = conn.execute("SELECT * FROM feed_models WHERE state='ready' ORDER BY file_id LIMIT 3").fetchall()
            for offset, (model, state) in enumerate(zip(models, states)):
                day = first+timedelta(days=offset)
                slot = f"{self.rules['account_id']}:{day.isoformat()}:{batch['id']}"
                request = 'auto-feed-'+hashlib.sha256(slot.encode()).hexdigest()
                due = int(datetime.combine(day, datetime.min.time(), scheduling.ZONE).replace(hour=12).timestamp())
                conn.execute('''INSERT INTO feed_auto_slots
                    (slot,due_at,policy,account_id,file_id,model_key,cycle,theme,request_id,state,post_id,batch_id)
                    VALUES(?,?,?,?,?,?,1,'generico',?,?,NULL,?)''',
                    (slot,due,self.rules['id'],self.rules['account_id'],model['file_id'],model['model_key'],request,state,batch['id']))
        return batch

    def test_progress_uses_current_account_and_policy_instead_of_latest_global_batch(self):
        self.preview_rules()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            current = conn.execute('SELECT id FROM feed_batches').fetchone()[0]
            for identity, account, policy in (('b'*32, '999999', self.rules['id']),
                                              ('c'*32, self.rules['account_id'], 'd'*32)):
                conn.execute('INSERT INTO feed_batches VALUES(?,?,?,?,?,?)',
                             (identity,account,'2026-11-05','2026-11-07',policy,self.now))
            before = conn.total_changes
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(conn.total_changes, before)
            self.assertEqual(progress['id'], current)
            self.assertEqual(progress['target'], 3)
            self.assertEqual(progress['drafts'], 1)
            self.assertEqual(progress['prepared'], 1)
            self.assertEqual(progress['total_slots'], 1)
            self.assertEqual(progress['slot_states'], {'draft': 1})
            self.assertEqual(auto.status(conn, self.directory)['batch']['id'], current)

    def test_progress_without_batch_reports_awaiting_start_and_completed_preview_reports_complete(self):
        self.preview_rules()
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertIsNone(progress['id'])
            self.assertEqual(progress['drafts'], 0)
            self.assertEqual(progress['waiting_reason'], 'awaiting_start')
        for _ in range(3):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['drafts'], 3)
            self.assertEqual(progress['prepared'], 3)
            self.assertEqual(progress['waiting_reason'], 'complete')
        before = self.client.downloads
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'waiting')
        self.assertEqual(self.client.downloads, before)

    def test_three_unfinished_reservations_are_resumed_before_batch_is_complete(self):
        batch = self.reserved_preview_batch()
        for _ in range(3):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['id'], batch['id'])
            self.assertEqual(progress['drafts'], 3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 3)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_batches').fetchone()[0], 1)

    def test_uncreated_held_reservation_is_released_and_missing_day_can_be_filled(self):
        batch = self.reserved_preview_batch(('held', 'reserved', 'reserved'))
        with app.connect() as conn:
            abandoned = dict(conn.execute("SELECT * FROM feed_auto_slots WHERE state='held'").fetchone())
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            self.assertIsNone(conn.execute('SELECT 1 FROM feed_auto_slots WHERE slot=?', (abandoned['slot'],)).fetchone())
            self.assertIsNone(conn.execute('SELECT 1 FROM feed_compositions WHERE request_id=?', (abandoned['request_id'],)).fetchone())
        for _ in range(2):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['id'], batch['id'])
            self.assertEqual(progress['prepared'], 3)
            self.assertEqual(progress['blocked_slots'], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 3)

    def assert_composed_held_reservation_is_protected(self, *, delete_post):
        self.preview_rules()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            original = dict(conn.execute('SELECT * FROM feed_auto_slots').fetchone())
            original_image = conn.execute('SELECT image_name FROM posts WHERE id=?', (original['post_id'],)).fetchone()[0]
            if delete_post:
                conn.execute('DELETE FROM posts WHERE id=?', (original['post_id'],))
            else:
                conn.execute("UPDATE posts SET caption='Conteúdo editado pelo proprietário',revision=1 WHERE id=?", (original['post_id'],))
            # A composição pode existir mesmo após uma interrupção ter deixado
            # o identificador do post ausente na reserva.
            conn.execute("UPDATE feed_auto_slots SET state='held',post_id=NULL WHERE slot=?", (original['slot'],))
        for _ in range(2):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'waiting')
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['drafts'], 2)
            self.assertEqual(progress['prepared'], 2)
            self.assertEqual(progress['blocked_slots'], 1)
            self.assertEqual(progress['waiting_reason'], 'batch_needs_review')
            retained = conn.execute('SELECT * FROM feed_auto_slots WHERE slot=?', (original['slot'],)).fetchone()
            self.assertEqual(retained['state'], 'held')
            self.assertIsNone(retained['post_id'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_compositions WHERE request_id=?', (original['request_id'],)).fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            post = conn.execute('SELECT * FROM posts WHERE id=?', (original['post_id'],)).fetchone()
            if delete_post:
                # SQLite pode reutilizar o ID do último post excluído. A arte
                # eliminada não pode ser restaurada nem receber novo conteúdo.
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts WHERE image_name=?', (original_image,)).fetchone()[0], 0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 2)
            else:
                self.assertEqual(post['revision'], 1)
                self.assertEqual(post['caption'], 'Conteúdo editado pelo proprietário')

    def test_held_reservation_with_deleted_composed_post_is_not_freed(self):
        self.assert_composed_held_reservation_is_protected(delete_post=True)

    def test_held_reservation_with_edited_composed_post_is_not_freed(self):
        self.assert_composed_held_reservation_is_protected(delete_post=False)

    def test_reused_post_identifier_does_not_count_a_deleted_draft_again(self):
        self.preview_rules()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            deleted = dict(conn.execute('SELECT * FROM feed_auto_slots').fetchone())
            conn.execute('DELETE FROM posts WHERE id=?', (deleted['post_id'],))
        # O próximo post pode receber o mesmo número no SQLite. Sua própria
        # composição precisa ser contada uma vez, sem ressuscitar a antiga.
        for _ in range(2):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 2)
            self.assertEqual(progress['drafts'], 2)
            self.assertEqual(progress['prepared'], 2)
            self.assertEqual(progress['blocked_slots'], 1)
            self.assertEqual(progress['waiting_reason'], 'batch_needs_review')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_compositions WHERE request_id=?', (deleted['request_id'],)).fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT state FROM feed_auto_slots WHERE slot=?', (deleted['slot'],)).fetchone()[0], 'draft')

    def test_ready_count_does_not_claim_previously_used_models_are_available(self):
        self.client = Client(6)
        self.index_all(lambda raw: 'generico')
        self.preview_rules()
        batch = auto._batch_days(app.connect, self.rules, self.now)
        with app.connect() as conn:
            for index, model in enumerate(conn.execute('SELECT * FROM feed_models ORDER BY file_id').fetchall()):
                request = f'auto-feed-historical-{index}'
                post_id = conn.execute("INSERT INTO posts(product,channel,caption,source,account_id) VALUES('Histórico','Instagram','Legenda','Rotina anterior','123456')").lastrowid
                conn.execute('INSERT INTO feed_compositions VALUES(?,?,?,?,?,?,?,?,?)',
                             (request,'historical','generico',0,1,model['file_id'],model['sha256'],post_id,self.now))
                conn.execute('''INSERT INTO feed_auto_slots
                    (slot,due_at,policy,account_id,file_id,model_key,cycle,theme,request_id,state,post_id,batch_id)
                    VALUES(?,?,?,?,?,?,1,'generico',?,'paused',?,'')''',
                    (f'historical-slot-{index}',self.now,'e'*32,self.rules['account_id'],model['file_id'],model['model_key'],request,post_id))
            for index in range(78):
                conn.execute('''INSERT INTO feed_models
                    (file_id,version,active,state,theme,sha256,model_key,visual)
                    VALUES(?, 'historical', 1, 'review', 'generico', ?, ?, '')''',
                    (f'review-image-{index}', 'f'*64, f'review-model-{index}'))
            progress = auto.batch_progress(conn, self.rules)
            self.assertEqual(progress['id'], batch['id'])
            self.assertEqual(progress['available_models'], 0)
            self.assertEqual(progress['used_ready_models'], 6)
            self.assertEqual(progress['review_models'], 78)
            self.assertEqual(progress['pending_models'], 0)
            self.assertEqual(progress['waiting_reason'], 'models_need_review')

    def test_repeated_preview_start_preserves_existing_draft_and_manual_queue(self):
        self.preview_rules()
        self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            draft = dict(conn.execute('SELECT * FROM posts').fetchone())
            batch = conn.execute('SELECT id FROM feed_batches').fetchone()[0]
            manual = conn.execute("INSERT INTO posts(product,channel,caption,source,account_id,publish_status) VALUES('Manual','Instagram','Legenda','Manual','123456','scheduled')").lastrowid
            conn.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(?,0,?,'queued')", (manual, self.now+3600))
        image = (self.directory/'media'/draft['image_name']).read_bytes()
        downloads = self.client.downloads
        with patch('feed_autonomy.pause_for_layout_review', side_effect=AssertionError('preview must resume')), \
                patch('feed_autonomy.enable', side_effect=AssertionError('policy must remain unchanged')):
            first = auto.start_preview(app.connect, self.directory)
            second = auto.start_preview(app.connect, self.directory)
        self.assertEqual(first['id'], self.rules['id'])
        self.assertEqual(second['id'], self.rules['id'])
        self.assertEqual(self.client.downloads, downloads)
        with app.connect() as conn:
            self.assertEqual(dict(conn.execute('SELECT * FROM posts WHERE id=?', (draft['id'],)).fetchone()), draft)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_batches').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT id FROM feed_batches').fetchone()[0], batch)
            self.assertEqual(conn.execute('SELECT state FROM post_schedule WHERE post_id=?', (manual,)).fetchone()[0], 'queued')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 1)
        self.assertEqual((self.directory/'media'/draft['image_name']).read_bytes(), image)

    def test_generic_mode_migrates_old_reviews_without_ocr_and_keeps_scheduled_post(self):
        self.index_all()
        self.assertEqual(self.tick(), 'prepared')
        with app.connect() as conn:
            original_post = dict(conn.execute('SELECT * FROM posts').fetchone())
            original_slot = dict(conn.execute('SELECT * FROM feed_auto_slots').fetchone())
            for row in conn.execute('SELECT file_id,version FROM feed_models').fetchall():
                old_version = json.dumps(json.loads(row['version'])[:3])
                conn.execute("UPDATE feed_models SET version=?,state='review',theme='' WHERE file_id=?", (old_version, row['file_id']))
        with patch('feed_autonomy.recognize', side_effect=AssertionError('must not read theme')), patch('feed_autonomy.engine', side_effect=AssertionError('must not require OCR')):
            before = self.client.downloads
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
            self.assertEqual(self.client.downloads, before+1)
            with patch('meta.verify_accounts', return_value={'accounts': self.accounts}):
                auto.enable(self.directory)
        with app.connect() as conn:
            self.assertEqual({r[0] for r in conn.execute('SELECT theme FROM feed_models')}, {'generico'})
            retained = dict(conn.execute('SELECT * FROM posts WHERE id=?', (original_post['id'],)).fetchone())
            self.assertEqual(retained, original_post)
            slots = conn.execute('SELECT * FROM feed_auto_slots ORDER BY rowid').fetchall()
            self.assertEqual(slots[1]['theme'], 'generico')
            self.assertNotEqual(slots[1]['model_key'], original_slot['model_key'])

    def test_new_model_is_found_before_cycle_restarts_even_with_fresh_cache(self):
        self.client = Client(3)
        self.index_all()
        for _ in range(3):
            self.assertEqual(self.tick(), 'prepared')
        os.utime(self.directory/drive.CATALOG_FILE, (self.now, self.now))
        extra = Client(4).data['original_model_0003']
        self.client.data['new_model_123456'] = extra
        self.assertEqual(self.tick(), 'indexing')
        with app.connect() as conn:
            self.assertEqual(conn.execute("SELECT state FROM feed_models WHERE file_id='new_model_123456'").fetchone()[0], 'ready')

    def test_similar_photos_are_held_instead_of_counted_as_distinct_models(self):
        with Image.open(io.BytesIO(self.client.data['original_model_0000'])) as image:
            output = io.BytesIO()
            ImageEnhance.Brightness(image).enhance(1.01).save(output, format='PNG')
        self.client.data['possible_other_photo'] = output.getvalue()
        self.index_all()
        with app.connect() as conn:
            self.assertEqual(conn.execute("SELECT state FROM feed_models WHERE file_id='possible_other_photo'").fetchone()[0], 'review')
            self.assertEqual(conn.execute("SELECT state FROM feed_models WHERE file_id='original_model_0000'").fetchone()[0], 'review')

    def test_review_package_and_hash_bound_import_require_no_daily_model_choice(self):
        self.index_all(lambda raw: '')
        path = auto.export_review(app.connect, self.directory, self.client)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'pagina-01.jpg', 'classificacao.json'})
            data = json.loads(archive.read('classificacao.json'))
        for value in data['models'].values():
            value['theme'] = 'ofertas'
        file_path = self.directory/'classificacao.json'
        first = next(iter(data['models']))
        digest = data['models'][first]['sha256']
        data['models'][first]['sha256'] = 'stale'
        drive.write_private(file_path, data)
        with self.assertRaises(ValueError):
            auto.import_review(app.connect, self.directory, file_path)
        with app.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM feed_models WHERE state='ready'").fetchone()[0], 0)
        data['models'][first]['sha256'] = digest
        drive.write_private(file_path, data)
        self.assertEqual(auto.import_review(app.connect, self.directory, file_path), 4)
        self.assertEqual(self.tick(), 'prepared')
