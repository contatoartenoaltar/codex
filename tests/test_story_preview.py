import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw
from stories import preview


class StoryPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.background = self.directory / 'background.jpg'
        shutil.copyfile(preview.TEMPLATE, self.background)

    def test_export_is_local_unbranded_and_preserves_original(self):
        original = self.background.read_bytes()
        target = self.directory / 'preview.jpg'
        with patch('socket.socket.connect', side_effect=AssertionError('Rede proibida')), \
             patch('sqlite3.connect', side_effect=AssertionError('Banco proibido')):
            metadata = preview.export(self.background, target)
        with Image.open(target) as image:
            self.assertEqual(image.size, (1080, 1920))
            self.assertEqual(image.format, 'JPEG')
        self.assertEqual(self.background.read_bytes(), original)
        self.assertFalse(metadata['branding'])
        self.assertTrue(metadata['layout_approved'])
        self.assertTrue(metadata['style_reference_approved'])
        self.assertFalse(metadata['publishing_enabled'])
        self.assertFalse(metadata['scheduling_enabled'])
        self.assertEqual(metadata['verse']['translation'], 'ARC')
        self.assertEqual(metadata['image_sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(json.loads(target.with_suffix('.json').read_text()), metadata)

    def test_every_verified_verse_fits_inside_editorial_area(self):
        image = Image.new('RGB', preview.SIZE)
        draw = ImageDraw.Draw(image)
        self.assertEqual(len({v['id'] for v in preview.verses()}), len(preview.verses()))
        for verse in preview.verses():
            with self.subTest(verse=verse['id']):
                content, font, bounds = preview.fit_text(draw, verse['text'], preview.TEXT_BOX)
                self.assertEqual(content.replace('\n', ' '), verse['text'])
                self.assertLessEqual(bounds[2] - bounds[0], preview.TEXT_BOX[2] - preview.TEXT_BOX[0])
                self.assertLessEqual(bounds[3] - bounds[1], preview.TEXT_BOX[3] - preview.TEXT_BOX[1])
                result, metadata = preview.render(self.background, verse_id=verse['id'])
                self.assertEqual(result.size, preview.SIZE)
                self.assertEqual(metadata['verse'], verse)
                prefix = verse['text'][:-len(verse['highlight'])].rstrip()
                self.assertEqual(prefix + ' ' + verse['highlight'], verse['text'])
                for bounds in metadata['text_bounds'].values():
                    self.assertGreaterEqual(bounds[0], preview.SAFE_BOX[0])
                    self.assertGreaterEqual(bounds[1], preview.SAFE_BOX[1])
                    self.assertLessEqual(bounds[2], preview.SAFE_BOX[2])
                    self.assertLessEqual(bounds[3], preview.SAFE_BOX[3])

    def test_banner_scenery_and_footer_remain_pixel_identical_outside_text(self):
        with Image.open(self.background) as original:
            original = original.convert('RGB')
        for verse in preview.verses():
            with self.subTest(verse=verse['id']):
                result, metadata = preview.render(self.background, verse_id=verse['id'])
                difference = ImageChops.difference(original, result)
                excluded = Image.new('L', preview.SIZE)
                draw = ImageDraw.Draw(excluded)
                for bounds in metadata['text_bounds'].values():
                    draw.rectangle((int(bounds[0])-2, int(bounds[1])-2,
                                    int(bounds[2])+2, int(bounds[3])+2), fill=255)
                difference.paste((0, 0, 0), mask=excluded)
                self.assertIsNone(difference.getbbox())

    def test_same_input_produces_identical_image_and_manifest(self):
        one = self.directory / 'one.jpg'
        two = self.directory / 'two.jpg'
        first = preview.export(None, one)
        second = preview.export(None, two)
        self.assertEqual(first, second)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        self.assertEqual(one.with_suffix('.json').read_bytes(), two.with_suffix('.json').read_bytes())

    def test_modified_font_is_blocked_before_export(self):
        layout = json.loads(preview.LAYOUT.read_text())
        layout['files']['fonts/greatvibes.ttf'] = '0' * 64
        changed = self.directory / 'changed-layout.json'
        changed.write_text(json.dumps(layout))
        target = self.directory / 'changed.jpg'
        with patch('stories.preview.LAYOUT', changed):
            with self.assertRaises(ValueError):
                preview.export(None, target)
        self.assertFalse(target.exists())

    def test_wrong_highlight_or_line_breaks_cannot_change_the_scripture(self):
        verse = preview.verses()[0]
        for change in ({'highlight': 'fortaleça.'}, {'highlight': 'ce.'},
                       {'lines': ['Texto que não consta no versículo']}):
            with self.subTest(change=change):
                with patch('stories.preview.verses', return_value=[verse | change]):
                    with self.assertRaises(ValueError):
                        preview.render()

    def test_verse_too_long_for_readable_type_is_not_exported(self):
        verse = preview.verses()[0] | {'text': 'Palavra ' * 150 + 'fortalece.'}
        verse.pop('lines')
        target = self.directory / 'too-long.jpg'
        with patch('stories.preview.verses', return_value=[verse]):
            with self.assertRaises(ValueError):
                preview.export(None, target)
        self.assertFalse(target.exists())

    def test_existing_image_or_manifest_are_never_overwritten(self):
        for suffix in ('.jpg', '.json'):
            with self.subTest(suffix=suffix):
                target = self.directory / ('existing-' + suffix[1:] + '.jpg')
                existing = target.with_suffix(suffix)
                existing.write_bytes(b'preservar')
                with self.assertRaises(FileExistsError):
                    preview.export(self.background, target)
                self.assertEqual(existing.read_bytes(), b'preservar')

    def test_input_cannot_be_replaced_even_with_jpeg_extension(self):
        source = self.directory / 'original.jpg'
        Image.new('RGB', (540, 960)).save(source)
        before = source.read_bytes()
        with self.assertRaises(ValueError):
            preview.export(source, source)
        self.assertEqual(source.read_bytes(), before)

    def test_invalid_ratio_unknown_verse_and_unreadable_image_leave_no_output(self):
        square = self.directory / 'square.png'
        Image.new('RGB', (100, 100)).save(square)
        invalid = self.directory / 'invalid.png'
        invalid.write_bytes(b'not an image')
        for source, verse in ((square, 'php-4-13'), (self.background, 'unknown'), (invalid, 'php-4-13')):
            with self.subTest(source=source, verse=verse):
                target = self.directory / 'invalid-output.jpg'
                with self.assertRaises((ValueError, OSError)):
                    preview.export(source, target, verse_id=verse)
                self.assertFalse(target.exists())
                self.assertFalse(target.with_suffix('.json').exists())

    def test_input_and_output_symlinks_are_rejected(self):
        link = self.directory / 'link.png'
        link.symlink_to(self.background)
        with self.assertRaises(ValueError):
            preview.render(link)
        target = self.directory / 'link.jpg'
        target.symlink_to(self.directory / 'missing.jpg')
        with self.assertRaises(FileExistsError):
            preview.export(self.background, target)
        self.assertTrue(target.is_symlink())

    def test_manifest_failure_removes_new_image_without_removing_other_files(self):
        target = self.directory / 'rollback.jpg'
        original_open = preview.os.open

        def fail_manifest(path, *args):
            if Path(path).suffix == '.json':
                raise OSError('Falha simulada')
            return original_open(path, *args)

        with patch('stories.preview.os.open', side_effect=fail_manifest):
            with self.assertRaises(OSError):
                preview.export(self.background, target)
        self.assertFalse(target.exists())
        self.assertTrue(self.background.exists())

    def test_oversized_text_is_refused_instead_of_cutting_the_verse(self):
        draw = ImageDraw.Draw(Image.new('RGB', preview.SIZE))
        with self.assertRaises(ValueError):
            preview.fit_text(draw, 'Palavra ' * 500, preview.TEXT_BOX)
