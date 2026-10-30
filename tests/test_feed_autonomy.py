from datetime import datetime
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
        self.assertEqual(self.tick(), 'prepared')
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
