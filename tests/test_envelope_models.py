import hashlib
import io
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from envelope_models import automation as models


def png(color=(90, 60, 30)):
    image = Image.new("RGB", (1536, 1024), color)
    # Evita que a verificação de imagem uniforme rejeite a amostra.
    for x in range(0, 1536, 64):
        image.paste(((x * 3) % 255, 120, 180), (x, 0, min(x + 32, 1536), 1024))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class SourceClient:
    def __init__(self):
        self.files = []
        for index, (theme, definition) in enumerate(models.THEMES.items()):
            for variant in range(2):
                data = png((40 + index * 20, 60 + variant * 20, 100))
                self.files.append({
                    "id": f"reference_{theme}_{variant:02d}",
                    "name": f"{definition['title']} modelo {variant}.png",
                    "mimeType": "image/png",
                    "md5Checksum": hashlib.md5(data, usedforsecurity=False).hexdigest(),
                    "data": data,
                })

    def catalog(self, folder):
        return {"complete": True, "folder_id": folder, "files": self.files}

    def download_image(self, item, limit=None):
        return item["data"]


class ImageClient:
    def __init__(self):
        self.calls = []

    def generate(self, theme, reference, mime):
        self.calls.append(theme)
        return png()


class OutputClient:
    def __init__(self):
        self.uploads = []

    def upload_png(self, folder, filename, data):
        self.uploads.append((folder, filename, data))
        return "created_drive_file_" + str(len(self.uploads)).zfill(2)


class EnvelopeModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.outputs = {theme: f"output_folder_{index:02d}"
                        for index, theme in enumerate(models.THEMES)}
        models.configure(self.directory, "source_folder_001", self.outputs)
        self.store = models.Store(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def test_configuration_starts_disabled_and_separates_every_folder(self):
        result = models.status(self.store)
        self.assertTrue(result["configured"])
        self.assertFalse(result["enabled"])
        self.assertEqual(result["daily_total"], 5)
        with self.assertRaises(models.EnvelopeError):
            models.configure(self.directory, "source_folder_001",
                             dict.fromkeys(models.THEMES, "same_output_folder"))

    def test_disabled_run_never_reads_drive_or_calls_generation(self):
        result = models.run(self.store, source_client=None, image_client=None,
                            output_client=None,
                            now=datetime(2026, 11, 10, 8, tzinfo=models.ZONE))
        self.assertEqual(result, {"status": "disabled", "created": 0,
                                  "day": "2026-11-10"})

    def test_daily_run_creates_one_candidate_per_theme_and_is_idempotent(self):
        with self.store.connect() as connection:
            connection.execute("UPDATE policy SET enabled=1 WHERE id=1")
        source, image, output = SourceClient(), ImageClient(), OutputClient()
        now = datetime(2026, 11, 10, 8, tzinfo=models.ZONE)
        result = models.run(self.store, source_client=source, image_client=image,
                            output_client=output, now=now)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["created"]), 5)
        self.assertEqual(image.calls, list(models.THEMES))
        self.assertEqual(len(output.uploads), 5)
        for theme, (folder, filename, data) in zip(models.THEMES, output.uploads):
            self.assertEqual(folder, self.outputs[theme])
            self.assertTrue(filename.startswith("2026-11-10-" + theme))
            with Image.open(io.BytesIO(data)) as final:
                self.assertEqual(final.size, models.OUTPUT_SIZE)
        again = models.run(self.store, source_client=source, image_client=image,
                           output_client=output, now=now)
        self.assertEqual(len(again["created"]), 0)
        self.assertEqual(set(again["skipped"]), set(models.THEMES))
        self.assertEqual(len(output.uploads), 5)

    def test_reference_rotation_prefers_unused_files(self):
        with self.store.connect() as connection:
            files = SourceClient().catalog("source")["files"]
            first = models.choose_reference(connection, {"files": files}, "dizimos")
            connection.execute("""INSERT INTO outputs
                (id,creation_day,theme,reference_id,reference_md5,filename,drive_id,sha256,state,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("row_0000000001", "2026-11-10", "dizimos", first["id"],
                 first["md5Checksum"], "one.png", "drive_file_001", "a" * 64, "review", 1))
            second = models.choose_reference(connection, {"files": files}, "dizimos")
        self.assertNotEqual(first["id"], second["id"])


if __name__ == "__main__":
    unittest.main()
