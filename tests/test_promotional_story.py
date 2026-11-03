import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

import promotional_story as story


class PromotionalStoryTests(unittest.TestCase):
    def source(self, color="#2b5f91"):
        image = Image.new("RGB", (700, 500), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((18, 18, 682, 482), outline="white", width=8)
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()

    def test_preview_is_vertical_local_and_does_not_change_source(self):
        raw = self.source()
        before = hashlib.sha256(raw).hexdigest()
        image, manifest = story.render(raw)
        self.assertEqual(image.size, (1080, 1920))
        self.assertEqual(manifest["source_sha256"], before)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), before)
        self.assertEqual(manifest["title"], "Envelopes com a sua IDENTIDADE")
        self.assertEqual(manifest["title_lines"], ["Envelopes", "com a sua", "IDENTIDADE"])
        self.assertNotIn("schedule", manifest)

    def test_daily_batch_has_ten_unique_drafts_and_approved_times(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for index in range(10):
                path = root / f"Modelo ({index + 1}).png"
                path.write_bytes(self.source(f"#{index + 1:02x}5588"))
                sources.append(path)
            batch = story.save_batch(sources, root / "batch", day="2026-11-03")
            self.assertFalse(batch["publishing_enabled"])
            self.assertEqual([item["time"] for item in batch["items"]], list(story.TIMES))
            self.assertEqual(len({item["source_sha256"] for item in batch["items"]}), 10)
            self.assertEqual(len({item["title"] for item in batch["items"]}), 10)
            self.assertEqual(len(list((root / "batch").glob("*.jpg"))), 10)
            self.assertEqual(json.loads((root / "batch" / "batch.json").read_text()), batch)

    def test_duplicate_or_wrong_count_batch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "one.png"
            source.write_bytes(self.source())
            with self.assertRaises(story.PreviewError):
                story.save_batch([source] * 10, Path(directory) / "batch", day="2026-11-03")
            with self.assertRaises(story.PreviewError):
                story.save_batch([source], Path(directory) / "batch", day="2026-11-03")

    def test_daily_cycle_uses_every_model_before_restarting_and_rotates_titles(self):
        catalog = [f"model-{index}" for index in range(27)]
        used = []
        days = []
        for _ in range(3):
            selected, used = story.daily_selection(catalog, used)
            self.assertEqual(len(selected), 10)
            self.assertEqual(len(set(selected)), 10)
            days.append(selected)
        self.assertEqual(len(set(days[0] + days[1] + days[2][:7])), 27)
        self.assertEqual(story.daily_phrase_indices(0), list(range(10)))
        self.assertEqual(story.daily_phrase_indices(1), list(range(1, 10)) + [0])


if __name__ == "__main__":
    unittest.main()
