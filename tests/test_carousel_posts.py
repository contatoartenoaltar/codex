from datetime import datetime, timedelta
import tempfile
from pathlib import Path
import unittest

from PIL import Image
from unittest.mock import patch

from carousel_posts import composer
from carousel_posts import http
from carousel_posts import wsgi as carousel_wsgi
from carousel_posts.queue import (APPLICATION_ID, Store, ZONE, cancel,
                                  enable_automatic, ensure_horizon, tick, verify_files)


class Transport:
    def __init__(self, account_id):
        self.account_id = account_id
        self.staged = 0
        self.children = 0
        self.parents = 0
        self.published = 0

    def verify_account(self, account_id):
        if account_id != self.account_id:
            raise ValueError("wrong account")

    def stage_image(self, image):
        self.staged += 1
        return {"id": str(100 + self.staged)}

    def create_carousel_child(self, image, *, staged_photo):
        self.children += 1
        return {"id": str(200 + self.children)}

    def container_status(self, container):
        return "FINISHED"

    def create_carousel(self, children, caption):
        self.parents += 1
        return {"id": "301"}

    def publish(self, container):
        self.published += 1
        return {"id": "401"}


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

    def test_tick_persists_each_remote_step_and_publishes_once(self):
        enable_automatic(self.store, "17841436823298466", confirmed=True)
        ensure_horizon(self.store, now=self.now)
        due = datetime.fromtimestamp(self.store.agenda()[0]["due_at"], ZONE)
        transport = Transport("17841436823298466")
        factory = lambda account_id: transport
        statuses = [tick(self.store, factory, now=due)["status"] for _ in range(8)]
        self.assertEqual(statuses, ["staging"] * 3 + ["processing"] * 3 +
                         ["publishing", "published"])
        row = self.store.agenda()[0]
        self.assertEqual((row["state"], row["remote_id"]), ("published", "401"))
        self.assertEqual((transport.staged, transport.children, transport.parents, transport.published),
                         (3, 3, 1, 1))
        self.assertEqual(tick(self.store, factory, now=due)["status"], "idle")
        self.assertEqual(transport.published, 1)

    def test_uncertain_remote_step_stops_for_review(self):
        enable_automatic(self.store, "17841436823298466", confirmed=True)
        ensure_horizon(self.store, now=self.now)
        due = datetime.fromtimestamp(self.store.agenda()[0]["due_at"], ZONE)
        transport = Transport("17841436823298466")
        transport.stage_image = lambda image: (_ for _ in ()).throw(ValueError("timeout"))
        result = tick(self.store, lambda account_id: transport, now=due)
        self.assertEqual(result["status"], "review")
        self.assertEqual(self.store.agenda()[0]["state"], "review")


class CarouselHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "carousel-http"
        self.origin = "https://artenoaltar.pythonanywhere.com"
        http.configure(self.directory, self.origin)
        self.key = (self.directory / http.KEY_FILE).read_text()
        self.environ = {
            "REQUEST_METHOD": "POST", "QUERY_STRING": "", "CONTENT_LENGTH": "0",
            "HTTP_HOST": "artenoaltar.pythonanywhere.com",
            "HTTP_AUTHORIZATION": "Bearer " + self.key,
        }

    def test_authenticated_empty_post_runs_tick(self):
        with patch("carousel_posts.http.tick", return_value={"status": "disabled"}) as execute:
            status, payload = http.handle(self.environ, self.directory, self.directory)
        self.assertEqual((status, payload), (200, {"status": "disabled"}))
        execute.assert_called_once()

    def test_wrong_key_and_request_body_are_rejected(self):
        wrong = dict(self.environ, HTTP_AUTHORIZATION="Bearer " + "x" * 48)
        self.assertEqual(http.handle(wrong, self.directory, self.directory)[0], 401)
        body = dict(self.environ, CONTENT_LENGTH="1")
        self.assertEqual(http.handle(body, self.directory, self.directory)[0], 400)

    def test_wsgi_delegates_existing_routes(self):
        environ = {"PATH_INFO": "/inicio"}
        with patch("promotional_stories.wsgi.application", return_value=[b"existing"]) as existing:
            result = carousel_wsgi.application(environ, lambda status, headers: None)
        self.assertEqual(result, [b"existing"])
        existing.assert_called_once()


if __name__ == "__main__":
    unittest.main()
