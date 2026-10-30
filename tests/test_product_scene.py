import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import feed_autonomy
import feed_composer
import product_scene as scene


class SceneTests(unittest.TestCase):
    def source(self):
        image = Image.new('RGB', (500, 350), '#b31382')
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 70, 440, 310), fill='white')
        draw.rectangle((75, 85, 425, 295), fill='#195c91')
        draw.rectangle((120, 130, 200, 210), fill='yellow')
        data = io.BytesIO()
        image.save(data, format='PNG')
        return data.getvalue()

    def test_real_detector_finds_whole_white_paper_without_background(self):
        raw = self.source()
        quad = scene.detect_quad(raw)
        self.assertLess(abs(quad[0][0]-60), 5)
        self.assertLess(abs(quad[0][1]-70), 5)
        self.assertLess(abs(quad[2][0]-440), 5)
        self.assertLess(abs(quad[2][1]-310), 5)
        before = hashlib.sha256(raw).hexdigest()
        result, _ = scene.render(raw, 0)
        self.assertEqual(result.size, (1080, 1350))
        self.assertEqual(hashlib.sha256(raw).hexdigest(), before)
        # O fundo magenta da fotografia não aparece como um retângulo na cena.
        self.assertNotIn((179, 19, 130), result.get_flattened_data())
        # A luz do papel pode variar discretamente a intensidade; o conteúdo
        # impresso continua amarelo, sem incorporar o fundo da fotografia.
        red, green, blue = result.getpixel((400, 800))
        self.assertGreaterEqual(red, 235)
        self.assertGreaterEqual(green, 235)
        self.assertLessEqual(blue, 10)

    def test_plain_background_is_held_and_invalid_quads_are_rejected(self):
        data = io.BytesIO()
        Image.new('RGB', (500, 350), 'white').save(data, format='PNG')
        with self.assertRaises(scene.CutoutError):
            scene.detect_quad(data.getvalue())
        for quad in ([[0, 0]]*4, [[-1, 2], [400, 2], [400, 300], [1, 300]],
                     [[10, 10], [400, 300], [400, 10], [10, 300]]):
            with self.assertRaises(scene.CutoutError):
                scene.validate_quad(quad, (500, 350))

    def test_warm_paper_on_bright_background_keeps_the_entire_print(self):
        image = Image.new('RGB', (600, 420), '#e6dfd0')
        draw = ImageDraw.Draw(image)
        # O fundo e o papel são claros: uma máscara branca pode juntar ambos.
        corners = [(85, 80), (540, 90), (535, 365), (75, 350)]
        draw.polygon(corners, fill='#fff4db')
        draw.polygon([(100, 98), (522, 108), (518, 346), (94, 332)], fill='#224c72')
        draw.text((160, 180), 'MODELO ORIGINAL', fill='white')
        output = io.BytesIO()
        image.save(output, format='PNG')
        quad = scene.detect_quad(output.getvalue())
        for found, expected in zip(quad, corners):
            self.assertLess(abs(found[0]-expected[0]), 5)
            self.assertLess(abs(found[1]-expected[1]), 5)

    def test_printed_rectangle_inside_white_background_is_not_paper(self):
        image = Image.new('RGB', (500, 350), 'white')
        ImageDraw.Draw(image).rectangle((60, 70, 440, 310), outline='black', width=3)
        output = io.BytesIO()
        image.save(output, format='PNG')
        with self.assertRaises(scene.CutoutError):
            scene.detect_quad(output.getvalue())

    def test_occluded_corner_is_held_instead_of_reconstructing_missing_print(self):
        image = Image.open(io.BytesIO(self.source())).convert('RGB')
        ImageDraw.Draw(image).polygon([(350, 235), (475, 210), (490, 340), (340, 340)], fill='#35251c')
        output = io.BytesIO()
        image.save(output, format='PNG')
        with self.assertRaises(scene.CutoutError):
            scene.detect_quad(output.getvalue())

    def test_fifteen_phrases_use_transparent_layers_on_the_continuous_scene(self):
        phrases = [feed_composer.phrase('generico', index) for index in range(15)]
        scene.validate_assets(phrases)
        for index in range(15):
            with Image.open(scene.TYPOGRAPHY/f'{index:02d}.png') as typography:
                self.assertEqual(typography.size, (1080, 450))
                self.assertEqual(typography.mode, 'RGBA')
                self.assertEqual(typography.getchannel('A').getextrema(), (0, 255))

    def test_transparent_copy_space_and_surrounding_scene_are_not_replaced(self):
        result, _ = scene.render(self.source(), 0)
        with Image.open(scene.MASTER) as image:
            master = image.convert('RGB')
        with Image.open(scene.TYPOGRAPHY/'00.png') as image:
            alpha = image.getchannel('A')
        transparent_samples = [(x, y) for x in range(0, 1080, 30)
                               for y in range(0, 450, 30) if alpha.getpixel((x, y)) == 0]
        self.assertGreater(len(transparent_samples), 50)
        for point in transparent_samples:
            self.assertEqual(result.getpixel(point), master.getpixel(point), point)
        # A mesma fotografia fornece o ambiente lateral e o CTA. Não há painel
        # opaco sobre o topo, nova moldura sobre a mesa ou rodapé refeito.
        for box in ((1020, 500, 1080, 1120), (0, 850, 140, 1100), (0, 1140, 1080, 1350)):
            self.assertEqual(result.crop(box).tobytes(), master.crop(box).tobytes(), box)

    def test_changed_typography_and_scene_geometry_invalidate_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)/'feed'
            shutil.copytree(scene.ASSETS, assets,
                            ignore=shutil.ignore_patterns('headers', 'template.jpg', 'verified_models.json'))
            with patch.object(scene, 'ASSETS', assets), \
                    patch.object(scene, 'MASTER', assets/'scene-v2.jpg'), \
                    patch.object(scene, 'SCENE_SPEC', assets/'scene-v2.json'), \
                    patch.object(scene, 'TYPOGRAPHY', assets/'typography'):
                approved = feed_autonomy.rules_hash()
                spec = json.loads(scene.SCENE_SPEC.read_text())
                spec['front'][0][0] += 1
                scene.SCENE_SPEC.write_text(json.dumps(spec))
                self.assertNotEqual(feed_autonomy.rules_hash(), approved)

                approved_geometry = feed_autonomy.rules_hash()
                art = scene.TYPOGRAPHY/'00.png'
                art.write_bytes(art.read_bytes()+b'changed')
                self.assertNotEqual(feed_autonomy.rules_hash(), approved_geometry)
                with self.assertRaises(scene.CutoutError):
                    scene.validate_assets()

    def test_typography_must_match_the_approved_phrase(self):
        with self.assertRaises(scene.CutoutError):
            scene.render(self.source(), 0, expected_phrase='Chamada sem aprovação')
