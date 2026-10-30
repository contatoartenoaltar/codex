import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageOps
import app
import drive_source
import feed_composer as feed


class Client:
    def __init__(self, original):
        self.original = original
        self.downloads = 0

    def catalog(self, folder):
        return {'folder_id': folder, 'checked_at': '2026-10-30', 'complete': True,
                'files': [{'id': 'model_original_1234', 'name': 'Modelo teste.png', 'mimeType': 'image/png'}]}

    def download_image(self, item):
        self.downloads += 1
        return self.original


class FeedComposerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.old_db = app.DB
        app.DB = self.directory / 'test.db'
        app.initialize()
        drive_source.write_private(self.directory / drive_source.CONFIG_FILE, {'folder_id': 'folder_original_1234'})
        source = Image.new('RGB', (400, 300), '#26374a')
        draw = ImageDraw.Draw(source)
        for box, color in [((0, 0, 50, 50), 'red'), ((350, 0, 399, 50), 'green'),
                           ((0, 250, 50, 299), 'blue'), ((350, 250, 399, 299), 'yellow')]:
            draw.rectangle(box, fill=color)
        output = io.BytesIO()
        source.save(output, format='PNG')
        self.original = output.getvalue()
        self.client = Client(self.original)

    def tearDown(self):
        app.DB = self.old_db
        self.tmp.cleanup()

    def compose(self, request_id, **changes):
        return feed.compose(app.connect, self.directory,
                            {'request_id': request_id, 'theme': 'ofertas', 'file_id': 'model_original_1234'} | changes,
                            self.client)

    def test_approved_calls_preserve_photo_and_button(self):
        original = feed.decode(self.original)
        with Image.open(feed.TEMPLATE) as base:
            footer = base.convert('RGB').crop((0, 1140, 1080, 1350)).tobytes()
        for theme in feed.PHRASES:
            for index in range(len(feed.PHRASES[theme])):
                image, box = feed.render(self.original, theme, index)
                self.assertEqual(image.size, (1080, 1350))
                expected = ImageOps.contain(original, (1080, 790), Image.Resampling.LANCZOS)
                self.assertEqual(image.crop(box).tobytes(), expected.tobytes())
                self.assertEqual(image.crop((0, 1140, 1080, 1350)).tobytes(), footer)
                self.assertTrue(feed.phrase(theme, index))

    def test_fifteen_generic_phrases_rotate_completely_before_repeating(self):
        self.assertEqual(len(feed.PHRASES['generico']), 15)
        for index in range(16):
            self.compose(f'generic-request-number-{index}', theme='generico')
            if index in (5, 10):
                app.initialize()
        with app.connect() as conn:
            rows = conn.execute("SELECT * FROM feed_compositions WHERE theme='generico' ORDER BY rowid").fetchall()
            self.assertEqual({r['phrase_index'] for r in rows[:15]}, set(range(15)))
            self.assertEqual({r['cycle'] for r in rows[:15]}, {1})
            self.assertEqual(rows[15]['cycle'], 2)
            self.assertNotEqual(rows[14]['phrase_index'], rows[15]['phrase_index'])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)

    def test_rotation_survives_restart_and_request_retry_never_duplicates(self):
        for index in range(7):
            request_id = f'test-request-number-{index}'
            result = self.compose(request_id)
            downloads = self.client.downloads
            retried = self.compose(request_id)
            self.assertEqual(result['post_id'], retried['post_id'])
            self.assertEqual(downloads, self.client.downloads)
            app.initialize()
        with app.connect() as conn:
            rows = conn.execute('SELECT * FROM feed_compositions ORDER BY rowid').fetchall()
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 7)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM post_schedule').fetchone()[0], 0)
            self.assertEqual({r['phrase_index'] for r in rows[:3]}, {0, 1, 2})
            self.assertEqual({r['phrase_index'] for r in rows[3:6]}, {0, 1, 2})
            self.assertTrue(all(a['phrase_index'] != b['phrase_index'] for a, b in zip(rows, rows[1:])))
            post = conn.execute('SELECT * FROM posts LIMIT 1').fetchone()
            self.assertEqual(post['publish_status'], 'draft')
            self.assertEqual(rows[0]['source_sha256'], hashlib.sha256(self.original).hexdigest())
            with Image.open(self.directory / 'media' / post['image_name']) as image:
                self.assertEqual(image.size, (1080, 1350))
        with self.assertRaises(ValueError):
            self.compose('test-request-number-0', theme='dizimos')

    def test_failed_creation_rolls_back_history_draft_and_media(self):
        original_upload = feed.publishing.upload
        def fail_after_upload(*args):
            return original_upload(*args)
        with patch('feed_composer.time.time', side_effect=RuntimeError('simulated failure')), patch('feed_composer.publishing.upload', side_effect=fail_after_upload):
            with self.assertRaises(RuntimeError):
                self.compose('failed-request-number-1')
        with app.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM feed_compositions').fetchone()[0], 0)
        self.assertEqual(list((self.directory / 'media').glob('*.jpg')), [])

    def test_unlisted_drive_file_and_unsupported_theme_are_rejected(self):
        for changes in ({'file_id': 'not_in_folder_1234'}, {'theme': 'unapproved'}):
            with self.assertRaises(ValueError):
                self.compose('rejected-request-number-1', **changes)
        self.assertEqual(self.client.downloads, 0)
