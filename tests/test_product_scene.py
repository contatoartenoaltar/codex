import hashlib
import io
import unittest

from PIL import Image, ImageDraw
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
        # A cor original da impressão permanece no interior do envelope.
        self.assertEqual(result.getpixel((400, 800)), (255, 255, 0))

    def test_plain_background_is_held_and_invalid_quads_are_rejected(self):
        data = io.BytesIO()
        Image.new('RGB', (500, 350), 'white').save(data, format='PNG')
        with self.assertRaises(scene.CutoutError):
            scene.detect_quad(data.getvalue())
        for quad in ([[0, 0]]*4, [[-1, 2], [400, 2], [400, 300], [1, 300]],
                     [[10, 10], [400, 300], [400, 10], [10, 300]]):
            with self.assertRaises(scene.CutoutError):
                scene.validate_quad(quad, (500, 350))

    def test_all_fifteen_header_assets_have_fixed_dimensions(self):
        for index in range(15):
            with Image.open(scene.ASSETS/'headers'/f'{index:02d}.jpg') as header:
                self.assertEqual(header.size, (1080, 345))
