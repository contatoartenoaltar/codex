import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw, ImageOps
import layout_preview as layouts


class LayoutPreviewTests(unittest.TestCase):
    def source(self, color):
        image = Image.new('RGB', (200, 150), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 18, 18), fill='red')
        draw.rectangle((180, 0, 199, 18), fill='green')
        draw.rectangle((0, 130, 18, 149), fill='blue')
        draw.rectangle((180, 130, 199, 149), fill='yellow')
        draw.rectangle((75, 50, 124, 99), fill='white', outline='black', width=3)
        return image

    def sample_archive(self, path):
        entries = []
        with zipfile.ZipFile(path, 'w') as archive:
            for index, color in enumerate(('navy', 'purple', 'orange')):
                name = f'originais/model-{index}.png'
                data = io.BytesIO()
                self.source(color).save(data, format='PNG')
                archive.writestr(name, data.getvalue())
                entries.append({'id': f'source-{index}', 'name': f'Modelo {index}', 'archive_path': name})
            archive.writestr('catalogo.json', json.dumps({'samples': entries}))

    def test_entire_resized_photo_is_preserved_without_text_or_corner_crop(self):
        source = self.source('white')
        for result in (layouts.feed(source), layouts.story(source), layouts.carousel(source)[1]):
            box = result.photo_box
            self.assertIsNotNone(box)
            expected = ImageOps.contain(source, (960, 720), Image.Resampling.LANCZOS)
            self.assertEqual(result.image.crop(box).tobytes(), expected.tobytes())
            self.assertTrue(0 <= box[0] < box[2] <= result.image.width)
            self.assertTrue(0 <= box[1] < box[3] <= result.image.height)

    def test_review_artifacts_have_expected_sizes_and_never_schedule_or_publish(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source = directory / 'samples.zip'
            self.sample_archive(source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch('publishing.publish', side_effect=AssertionError('must not publish')), patch('scheduling.save', side_effect=AssertionError('must not schedule')):
                result = layouts.build_review(source, directory / 'review')
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            with zipfile.ZipFile(result['zip']) as archive:
                metadata = json.loads(archive.read('proposta.json'))
                self.assertFalse(metadata['approved'])
                self.assertFalse(metadata['official_logo_supplied'])
                self.assertEqual(len(metadata['sources']), 3)
                for key, size in [('feed', (1080, 1350)), ('story', (1080, 1920)),
                                  ('carousel-01', (1080, 1350)), ('carousel-02', (1080, 1350)),
                                  ('carousel-03', (1080, 1350))]:
                    with Image.open(io.BytesIO(archive.read(key + '.jpg'))) as image:
                        self.assertEqual(image.size, size)
                    self.assertLess(len(archive.read(key + '.jpg')), 5 * 1024 * 1024)
            self.assertFalse((directory / 'arte-no-altar.db').exists())

    def test_duplicate_sources_or_path_traversal_are_rejected(self):
        for malicious in ('originais/../../secret.png', '/originais/secret.png'):
            with tempfile.TemporaryDirectory() as name:
                path = Path(name) / 'samples.zip'
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr(malicious, b'not-an-image')
                    archive.writestr('catalogo.json', json.dumps({'samples': []}))
                with self.assertRaises(ValueError):
                    layouts.read_samples(path)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'samples.zip'
            image = io.BytesIO()
            self.source('white').save(image, format='PNG')
            with zipfile.ZipFile(path, 'w') as archive:
                entries = []
                for index in range(3):
                    member = f'originais/{index}.png'
                    archive.writestr(member, image.getvalue())
                    entries.append({'id': str(index), 'name': 'Repetida', 'archive_path': member})
                archive.writestr('catalogo.json', json.dumps({'samples': entries}))
            with self.assertRaises(ValueError):
                layouts.read_samples(path)

    def test_source_archive_is_never_overwritten_by_output(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'proposta-layouts.zip'
            self.sample_archive(path)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                layouts.build_review(path, Path(name) / 'review')
            self.assertEqual(path.read_bytes(), before)
