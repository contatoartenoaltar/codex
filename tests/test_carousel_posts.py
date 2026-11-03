from datetime import datetime, timedelta
import tempfile
from pathlib import Path
import unittest

from PIL import Image

from carousel_posts import composer
from carousel_posts.queue import (APPLICATION_ID, Store, ZONE, cancel,
                                  enable_automatic, ensure_horizon, verify_files)


class CarouselComposerTests(unittest.TestCase):
    def test_catalog_and_visual_library_are_complete(self):
        self.assertEqual(len(composer.catalog()), 14)
        self.assertEqual(len(composer.rules_hash()), 64)

    def test_shipping_reuses_approved_art_and_other_topic_has_three_slides(self):
        for ident in ("formas-de-envio", "localizacao"):
            slides = composer.render(ident)
            self.assertEqual(len(slides), 3)
            self.assertTrue(all(image.size == (1080, 1350) for image in slides))


class CarouselQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "carousel")
        self.store.initialize()
        self.now = datetime(2026, 11, 3, 9, 0, tzinfo=ZONE)  # terça-feira

    def test_isolated_and_disabled_by_default(self):
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA application_id").fetchone()[0], APPLICATION_ID)
            self.assertFalse(connection.execute("SELECT enabled FROM policy WHERE id=1").fetchone()[0])
        self.assertEqual(ensure_horizon(self.store, now=self.now), {"status": "disabled"})

    def test_activation_prepares_three_monday_wednesday_friday_carousels(self):
        enable_automatic(self.store, "17841436823298466", confirmed=True)
        result = ensure_horizon(self.store, now=self.now)
        self.assertEqual(result["status"], "queued")
        rows = self.store.agenda()
        self.assertEqual(len(rows), 3)
        due = [datetime.fromtimestamp(row["due_at"], ZONE) for row in rows]
        self.assertEqual([value.weekday() for value in due], [2, 4, 0])
        self.assertEqual([value.strftime("%H:%M") for value in due], ["12:00"] * 3)
        self.assertEqual(len({row["faq_id"] for row in rows}), 3)
        for row in rows:
            self.assertEqual(len(verify_files(self.store, row["id"])), 3)

    def test_rotation_uses_all_fourteen_before_repeating(self):
        enable_automatic(self.store, "17841436823298466", confirmed=True)
        for day in range(30):
            ensure_horizon(self.store, now=self.now + timedelta(days=day))
        rows = self.store.agenda()
        first = rows[:14]
        self.assertEqual(len({row["faq_id"] for row in first}), 14)
        self.assertTrue(all(row["cycle"] == 1 for row in first))
        if len(rows) > 14:
            self.assertEqual(rows[14]["cycle"], 2)

    def test_cancel_keeps_topic_in_rotation_history(self):
        enable_automatic(self.store, "17841436823298466", confirmed=True)
        ensure_horizon(self.store, now=self.now)
        row = self.store.agenda()[0]
        self.assertEqual(cancel(self.store, row["id"])["state"], "cancelled")
        self.assertEqual(self.store.agenda()[0]["state"], "cancelled")

    def test_changed_visual_rules_stop_automatic_generation(self):
        enable_automatic(self.store, "17841436823298466", confirmed=True)
        with self.store.connect() as connection:
            connection.execute("UPDATE policy SET rules_hash='old' WHERE id=1")
        self.assertEqual(ensure_horizon(self.store, now=self.now)["status"], "review")
        with self.store.connect() as connection:
            self.assertFalse(connection.execute("SELECT enabled FROM policy WHERE id=1").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
