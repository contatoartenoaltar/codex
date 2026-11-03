import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import content_schedule


class ContentScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.verse = root / "verse"
        self.promotional = root / "promotional"
        self.now = 1_800_000_000
        self.verse_name = "1" * 32 + ".jpg"
        self.promotional_name = "2" * 32 + ".jpg"
        self._queue(self.verse, "story-queue.sqlite3", content_schedule.VERSE_APPLICATION_ID,
                    "verse_json TEXT NOT NULL",
                    ("verse-1", self.now + 600, json.dumps({"reference": "Filipenses 4:13"}),
                     self.verse_name, "queued"))
        self._queue(self.promotional, "promotional-story-queue.sqlite3",
                    content_schedule.PROMOTIONAL_APPLICATION_ID, "model_name TEXT NOT NULL",
                    ("promo-1", self.now + 300, "Modelo 12.png", self.promotional_name, "queued"))
        (self.promotional / "media" / self.promotional_name).with_suffix(".json").write_text(
            json.dumps({"title": "Envelopes com propósito"}), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "ARTENOALTAR_STORIES_DIR": str(self.verse),
            "ARTENOALTAR_PROMOTIONAL_STORIES_DIR": str(self.promotional),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _queue(self, directory, database, application_id, extra_column, row):
        media = directory / "media"
        media.mkdir(parents=True)
        connection = sqlite3.connect(directory / database)
        connection.execute(f"PRAGMA application_id={application_id}")
        connection.execute(f"""CREATE TABLE slots(
            id TEXT PRIMARY KEY,due_at INTEGER NOT NULL,{extra_column},
            filename TEXT NOT NULL,state TEXT NOT NULL)""")
        connection.execute("INSERT INTO slots VALUES(?,?,?,?,?)", row)
        connection.commit()
        connection.close()
        image = Image.new("RGB", (40, 60), "white")
        image.save(media / row[3], "JPEG")

    def test_combines_verified_story_queues_in_time_order_without_writing(self):
        before = (self.promotional / "promotional-story-queue.sqlite3").read_bytes()
        items = content_schedule.agenda(now=self.now)
        self.assertEqual([item["kind"] for item in items], ["promotional", "verse"])
        self.assertEqual(items[0]["product"], "Envelopes com propósito")
        self.assertEqual(items[1]["product"], "Versículo · Filipenses 4:13")
        self.assertEqual(items[0]["channel"], "Instagram Story")
        self.assertEqual((self.promotional / "promotional-story-queue.sqlite3").read_bytes(), before)

    def test_thumbnail_requires_login_route_to_request_a_file_owned_by_the_queue(self):
        payload = content_schedule.image("promotional", self.promotional_name)
        self.assertTrue(payload.startswith(b"\xff\xd8"))
        with self.assertRaises(ValueError):
            content_schedule.image("promotional", "3" * 32 + ".jpg")
        with self.assertRaises(ValueError):
            content_schedule.image("unknown", self.promotional_name)

    def test_draft_expired_and_unverified_databases_are_not_exposed(self):
        with sqlite3.connect(self.verse / "story-queue.sqlite3") as connection:
            connection.execute("UPDATE slots SET state='draft'")
        with sqlite3.connect(self.promotional / "promotional-story-queue.sqlite3") as connection:
            connection.execute("PRAGMA application_id=1")
        self.assertEqual(content_schedule.agenda(now=self.now), [])


if __name__ == "__main__":
    unittest.main()
