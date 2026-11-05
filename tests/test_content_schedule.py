import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import content_schedule
from carousel_posts.queue import Store as CarouselStore


class ContentScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.verse = root / "verse"
        self.promotional = root / "promotional"
        self.carousel = root / "carousel"
        self.now = 1_800_000_000
        self.verse_name = "1" * 32 + ".jpg"
        self.promotional_name = "2" * 32 + ".jpg"
        self._queue(self.verse, "story-queue.sqlite3", content_schedule.VERSE_APPLICATION_ID,
                    "verse_json TEXT NOT NULL",
                    ("1" * 32, self.now + 600, json.dumps({"reference": "Filipenses 4:13"}),
                     self.verse_name, "queued"))
        self._queue(self.promotional, "promotional-story-queue.sqlite3",
                    content_schedule.PROMOTIONAL_APPLICATION_ID, "model_name TEXT NOT NULL",
                    ("2" * 32, self.now + 300, "Modelo 12.png", self.promotional_name, "queued"))
        (self.promotional / "media" / self.promotional_name).with_suffix(".json").write_text(
            json.dumps({"title": "Envelopes com propósito"}), encoding="utf-8")
        carousel_store = CarouselStore(self.carousel)
        carousel_store.initialize()
        carousel_id = "3" * 32
        carousel_media = self.carousel / "media" / carousel_id
        carousel_media.mkdir()
        carousel_names = [f"localizacao-0{position}.jpg" for position in (1, 2, 3)]
        for carousel_name in carousel_names:
            Image.new("RGB", (1080, 1350), "black").save(carousel_media / carousel_name, "JPEG")
        with carousel_store.connect() as connection:
            connection.execute(
                "INSERT INTO carousels(id,faq_id,cycle,due_at,state,caption,manifest,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (carousel_id, "localizacao", 1, self.now + 450, "queued", "Legenda", "{}", self.now))
            for position, carousel_name in enumerate(carousel_names, 1):
                connection.execute(
                    "INSERT INTO slides(carousel_id,position,filename,image_hash) VALUES(?,?,?,?)",
                    (carousel_id, position, f"media/{carousel_id}/{carousel_name}", "hash"))
        self.environment = patch.dict(os.environ, {
            "ARTENOALTAR_STORIES_DIR": str(self.verse),
            "ARTENOALTAR_PROMOTIONAL_STORIES_DIR": str(self.promotional),
            "ARTENOALTAR_CAROUSELS_DIR": str(self.carousel),
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
            filename TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL DEFAULT '')""")
        connection.execute("CREATE TABLE policy(id INTEGER PRIMARY KEY,account_id TEXT NOT NULL)")
        connection.execute("INSERT INTO policy VALUES(1,'17841436823298466')")
        connection.execute("CREATE TABLE policy_events(action TEXT,account_id TEXT,created_at INTEGER)")
        connection.execute(
            f"INSERT INTO slots(id,due_at,{extra_column.split()[0]},filename,state) VALUES(?,?,?,?,?)", row)
        connection.commit()
        connection.close()
        image = Image.new("RGB", (40, 60), "white")
        image.save(media / row[3], "JPEG")

    def test_combines_verified_story_queues_in_time_order_without_writing(self):
        before = (self.promotional / "promotional-story-queue.sqlite3").read_bytes()
        items = content_schedule.agenda(now=self.now)
        self.assertEqual([item["kind"] for item in items], ["promotional", "carousel", "verse"])
        self.assertEqual(items[0]["product"], "Envelopes com propósito")
        self.assertEqual(items[1]["product"], "Onde vocês estão localizados?")
        self.assertEqual(items[2]["product"], "Versículo · Filipenses 4:13")
        self.assertEqual(items[0]["channel"], "Instagram Story")
        self.assertEqual(items[1]["channel"], "Instagram Carrossel")
        self.assertEqual(len(items[1]["image_urls"]), 3)
        self.assertEqual((self.promotional / "promotional-story-queue.sqlite3").read_bytes(), before)

    def test_thumbnail_requires_login_route_to_request_a_file_owned_by_the_queue(self):
        payload = content_schedule.image("promotional", self.promotional_name)
        self.assertTrue(payload.startswith(b"\xff\xd8"))
        with self.assertRaises(ValueError):
            content_schedule.image("promotional", "3" * 32 + ".jpg")
        with self.assertRaises(ValueError):
            content_schedule.image("unknown", self.promotional_name)
        carousel_payload = content_schedule.image("carousel", "3" * 32 + "-01.jpg")
        self.assertTrue(carousel_payload.startswith(b"\xff\xd8"))
        self.assertTrue(content_schedule.image("carousel", "3" * 32 + "-03.jpg").startswith(b"\xff\xd8"))

    def test_confirmed_cancel_only_removes_the_selected_queued_item_from_the_agenda(self):
        item = content_schedule.agenda(now=self.now)[0]
        with self.assertRaises(ValueError):
            content_schedule.cancel(item["id"], item["due_at"], confirmed=False)
        result = content_schedule.cancel(item["id"], item["due_at"], confirmed=True)
        self.assertTrue(result["cancelled"])
        self.assertEqual([entry["kind"] for entry in content_schedule.agenda(now=self.now)],
                         ["carousel", "verse"])
        with sqlite3.connect(self.promotional / "promotional-story-queue.sqlite3") as connection:
            self.assertEqual(connection.execute("SELECT state FROM slots").fetchone()[0], "cancelled")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM policy_events").fetchone()[0], 1)

    def test_confirmed_cancel_removes_selected_carousel_only(self):
        item = next(entry for entry in content_schedule.agenda(now=self.now)
                    if entry["kind"] == "carousel")
        result = content_schedule.cancel(item["id"], item["due_at"], confirmed=True)
        self.assertTrue(result["cancelled"])
        self.assertNotIn("carousel", [entry["kind"] for entry in content_schedule.agenda(now=self.now)])
        with sqlite3.connect(self.carousel / "carousel-queue.sqlite3") as connection:
            self.assertEqual(connection.execute("SELECT state FROM carousels").fetchone()[0], "cancelled")

    def test_review_items_and_unverified_databases_are_not_exposed(self):
        with sqlite3.connect(self.verse / "story-queue.sqlite3") as connection:
            connection.execute("UPDATE slots SET state='review'")
        with sqlite3.connect(self.promotional / "promotional-story-queue.sqlite3") as connection:
            connection.execute("PRAGMA application_id=1")
        with sqlite3.connect(self.carousel / "carousel-queue.sqlite3") as connection:
            connection.execute("UPDATE carousels SET state='review'")
        self.assertEqual(content_schedule.agenda(now=self.now), [])


if __name__ == "__main__":
    unittest.main()
