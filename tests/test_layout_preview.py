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

    def test_transparent_logo_remains_unchanged_and_is_rendered_on_white(self):
        logo = Image.new('RGBA', (575, 230), (0, 0, 0, 0))
        draw = ImageDraw.Draw(logo)
        draw.rectangle((70, 0, 504, 229), fill='black')
        draw.rectangle((200, 70, 370, 160), fill=(230, 150, 20, 128))
        before = logo.tobytes()
        for height in (1350, 1920):
            canvas = layouts.Canvas(height, logo)
            mark = ImageOps.contain(logo, (336, 104), Image.Resampling.LANCZOS)
            expected = Image.new('RGBA', mark.size, '#fffdf8')
            expected.alpha_composite(mark)
            x = 64 + (360 - mark.width) // 2
            y = (216 if height == 1920 else 28) + (116 - mark.height) // 2
            actual = canvas.result().image.crop((x, y, x + mark.width, y + mark.height))
            self.assertEqual(actual.tobytes(), expected.convert('RGB').tobytes())
        self.assertEqual(logo.tobytes(), before)
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            source = directory / 'samples.zip'
            self.sample_archive(source)
            logo_path = directory / 'logo.png'
            logo.save(logo_path)
            original_bytes = logo_path.read_bytes()
            result = layouts.build_review(source, directory / 'review', logo_path)
            self.assertTrue(result['official_logo_supplied'])
            metadata = json.loads((directory / 'review' / 'proposta.json').read_text())
            self.assertEqual(metadata['logo']['sha256'], hashlib.sha256(original_bytes).hexdigest())
            self.assertEqual(metadata['logo']['size'], [575, 230])
            self.assertEqual(logo_path.read_bytes(), original_bytes)
            # Preserva também os modelos ao aplicar a logo em todos os formatos.
            expected = ImageOps.contain(self.source('navy'), (960, 720), Image.Resampling.LANCZOS)
            box = metadata['canvases']['feed']['photo_box']
            with Image.open(directory / 'review' / 'feed.png') as final:
                self.assertEqual(final.crop(box).tobytes(), expected.tobytes())
