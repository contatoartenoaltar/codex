from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import drive_source
import promotional_story
from promotional_stories import http
from promotional_stories import wsgi as promo_wsgi
from promotional_stories.queue import (APPLICATION_ID, Store, ZONE, configure_live,
    cleanup_media, enable_daily, enable_live, prepare_batch, queue_batch, reject_batch,
    run_daily, run_daily_step, tick)
from stories.queue import APPLICATION_ID as VERSE_APPLICATION_ID


class Drive:
    def __init__(self, count=23):
        self.items = [{"id": f"model_{index:04d}", "name": f"Modelo {index}.png",
                       "mimeType": "image/png", "path": ["Artes", f"Modelo {index}.png"]}
                      for index in range(count)]
        self.downloads = 0
        self.downloaded_ids = []

    def catalog(self, folder):
        return {"complete": True, "folder_id": folder, "files": list(self.items)}

    def download_image(self, item):
        self.downloads += 1
        self.downloaded_ids.append(item["id"])
        image = Image.new("RGB", (100, 60), (self.downloads % 255, 20, 30))
        output = io.BytesIO()
        image.save(output, "PNG")
        return output.getvalue()


def fake_render(raw, phrase_index):
    lines = promotional_story.PHRASES[phrase_index]
    image = Image.new("RGB", promotional_story.SIZE, (phrase_index * 20, 30, 40))
    return image, {"version": "promotional-story-envelope-face-v5",
                   "cutout_version": "paper-quad-v2",
                   "rules_hash": promotional_story.rules_hash(),
                   "size": list(promotional_story.SIZE), "title": " ".join(lines),
                   "title_lines": list(lines), "phrase_index": phrase_index,
                   "cta": promotional_story.CTA, "phone": promotional_story.PHONE,
                   "source_sha256": hashlib.sha256(raw).hexdigest()}


class Transport:
    simulation = False
    requires_staging = True

    def __init__(self, account_id="123456"):
        self.account_id = account_id
        self.published = 0

    def verify_account(self, account_id):
        return {"id": account_id, "username": "arte.no.altar", "account_type": "BUSINESS",
                "stories_allowed": True}

    def stage_image(self, image):
        return {"id": "photo1"}

    def create_container(self, image, **options):
        return {"id": "container1"}

    def container_status(self, container):
        return "FINISHED"

    def publish(self, container):
        self.published += 1
        return {"id": "published1"}


class PromotionalQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.directory = root / "promotional"
        self.drive_directory = root / "drive"
        drive_source.write_private(self.drive_directory / drive_source.CONFIG_FILE,
                                   {"folder_id": "folder_original_1234"})
        self.store = Store(self.directory)
        self.store.initialize()
        self.drive = Drive()
        self.now = datetime(2026, 11, 3, 1, 0, tzinfo=ZONE)
        self.render = patch("promotional_stories.queue.promotional_story.render", side_effect=fake_render)
        self.render_mock = self.render.start()
        self.addCleanup(self.render.stop)

    def prepare(self):
        return prepare_batch(self.store, self.drive_directory, client=self.drive, now=self.now)

    def test_storage_is_distinct_and_disabled_by_default(self):
        self.assertNotEqual(APPLICATION_ID, VERSE_APPLICATION_ID)
        self.assertEqual(self.store.path.name, "promotional-story-queue.sqlite3")
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA application_id").fetchone()[0], APPLICATION_ID)
            policy = conn.execute("SELECT * FROM policy").fetchone()
        self.assertEqual((policy["mode"], policy["enabled"], policy["account_id"]), ("live", 0, ""))

    def test_previous_schema_adds_batch_tracking_without_enabling(self):
        directory = Path(self.temp.name) / "previous-promotional"
        directory.mkdir()
        path = directory / "promotional-story-queue.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("""CREATE TABLE model_history(
            cycle INTEGER NOT NULL, model_id TEXT NOT NULL, PRIMARY KEY(cycle,model_id))""")
        connection.execute("""CREATE TABLE batches(
            id TEXT PRIMARY KEY, day TEXT NOT NULL UNIQUE, cycle INTEGER NOT NULL,
            created_at INTEGER NOT NULL)""")
        connection.execute("INSERT INTO model_history VALUES(1,'existing-model')")
        connection.commit()
        connection.close()
        previous = Store(directory)
        previous.initialize()
        with previous.connect() as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(model_history)")}
            batch_columns = {row[1] for row in connection.execute("PRAGMA table_info(batches)")}
            policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
            history = connection.execute(
                "SELECT cycle,model_id,batch_id FROM model_history").fetchone()
        self.assertIn("batch_id", columns)
        self.assertIn("automatic", batch_columns)
        self.assertEqual(tuple(history), (1, "existing-model", ""))
        self.assertFalse(policy["enabled"])

    def activate_daily(self):
        batch = self.prepare()["batch_id"]
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        configure_live(self.store, "123456", confirmed=True)
        enable_live(self.store, confirmed=True, now=self.now)
        enable_daily(self.store, self.drive_directory, confirmed=True, now=self.now)
        return batch

    def test_daily_generation_requires_reviewed_live_batch_and_confirmation(self):
        with self.assertRaises(ValueError):
            enable_daily(self.store, self.drive_directory, confirmed=True, now=self.now)
        batch = self.prepare()["batch_id"]
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        configure_live(self.store, "123456", confirmed=True)
        enable_live(self.store, confirmed=True, now=self.now)
        with self.assertRaises(ValueError):
            enable_daily(self.store, self.drive_directory, now=self.now)
        enable_daily(self.store, self.drive_directory, confirmed=True, now=self.now)
        with self.store.connect() as connection:
            automation = connection.execute("SELECT * FROM daily_automation").fetchone()
        self.assertTrue(automation["enabled"])
        self.assertEqual(automation["rules_hash"], promotional_story.rules_hash())

    def test_daily_run_prepares_exactly_one_future_batch_per_local_day(self):
        self.activate_daily()
        result = run_daily(self.store, client=self.drive, now=self.now)
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(self.store.agenda()), 20)
        self.assertEqual({row["state"] for row in self.store.agenda()}, {"queued"})
        downloads = self.drive.downloads
        self.assertEqual(run_daily(self.store, client=self.drive, now=self.now)["status"], "idle")
        self.assertEqual(self.drive.downloads, downloads)
        self.assertEqual(run_daily(
            self.store, client=self.drive, now=self.now+timedelta(days=1))["status"], "queued")
        self.assertEqual(len(self.store.agenda()), 30)

    def test_daily_run_disables_itself_when_approved_rules_change(self):
        self.activate_daily()
        with patch("promotional_stories.queue.promotional_story.rules_hash",
                   return_value="0" * 64):
            self.assertEqual(run_daily(self.store, client=self.drive, now=self.now)["status"], "review")
        with self.store.connect() as connection:
            automation = connection.execute("SELECT * FROM daily_automation").fetchone()
        self.assertFalse(automation["enabled"])

    def test_daily_steps_use_existing_external_trigger_and_queue_tenth_art(self):
        self.activate_daily()
        batch_id = None
        for completed in range(1, 10):
            result = run_daily_step(self.store, client=self.drive, now=self.now)
            batch_id = batch_id or result["batch_id"]
            self.assertEqual(result, {"status": "preparing", "batch_id": batch_id,
                                      "completed": completed, "total": 10})
            with self.store.connect() as connection:
                drafts = connection.execute(
                    "SELECT COUNT(*) FROM slots WHERE state='draft'").fetchone()[0]
            self.assertEqual(drafts, completed)
        result = run_daily_step(self.store, client=self.drive, now=self.now)
        self.assertEqual(result, {"status": "queued", "batch_id": batch_id})
        self.assertEqual(len(self.store.agenda()), 20)
        self.assertEqual({row["state"] for row in self.store.agenda()}, {"queued"})
        self.assertEqual(run_daily_step(self.store, client=self.drive, now=self.now)["status"], "idle")

    def test_daily_step_resumes_after_temporary_drive_failure(self):
        self.activate_daily()
        failing = Mock()
        failing.catalog.side_effect = ValueError("temporary")
        with self.assertRaises(ValueError):
            run_daily_step(self.store, client=failing, now=self.now)
        result = run_daily_step(self.store, client=self.drive, now=self.now)
        self.assertEqual(result["status"], "preparing")
        self.assertEqual(result["completed"], 1)

    def test_prepare_creates_ten_unique_models_titles_and_exact_times_as_drafts(self):
        drive_config = (self.drive_directory / drive_source.CONFIG_FILE).read_bytes()
        result = self.prepare()
        rows = self.store.agenda()
        self.assertTrue(result["created"])
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row["model_id"] for row in rows}), 10)
        self.assertEqual(len({row["phrase_index"] for row in rows}), 10)
        self.assertEqual({row["state"] for row in rows}, {"draft"})
        self.assertEqual([datetime.fromtimestamp(row["due_at"], ZONE).strftime("%H:%M") for row in rows],
                         list(promotional_story.TIMES))
        self.assertEqual(self.drive.downloads, 10)
        self.assertEqual((self.drive_directory / drive_source.CONFIG_FILE).read_bytes(), drive_config)
        self.assertFalse((self.drive_directory / drive_source.CATALOG_FILE).exists())
        self.assertFalse(prepare_batch(self.store, self.drive_directory, client=self.drive, now=self.now)["created"])
        self.assertEqual(self.drive.downloads, 10)

    def test_catalog_cycle_is_consumed_before_reuse_and_day_never_duplicates(self):
        batches = []
        for day_index in range(3):
            result = prepare_batch(self.store, self.drive_directory, client=self.drive,
                                   now=self.now + timedelta(days=day_index))
            batches.append(result["batch_id"])
            with self.store.connect() as conn:
                conn.execute("UPDATE slots SET state='published' WHERE batch_id=?", (result["batch_id"],))
        with self.store.connect() as conn:
            days = [[row[0] for row in conn.execute(
                "SELECT model_id FROM slots WHERE batch_id=? ORDER BY position", (batch,))] for batch in batches]
        self.assertEqual(len(set(days[0]) | set(days[1])), 20)
        self.assertEqual(len(set(days[2])), 10)
        self.assertEqual(len((set(days[0]) | set(days[1]) | set(days[2]))), 23)

    def test_available_models_are_shuffled_before_a_new_batch_is_composed(self):
        randomizer = Mock()
        randomizer.shuffle.side_effect = lambda values: values.reverse()
        expected = sorted(
            self.drive.items, key=lambda item: (tuple(item["path"]), item["id"]))[-1]["id"]
        with patch("promotional_stories.queue.secrets.SystemRandom", return_value=randomizer):
            self.prepare()
        self.assertEqual(self.store.agenda()[0]["model_id"], expected)
        self.assertEqual(randomizer.shuffle.call_count, 2)

    def test_queue_requires_confirmation_and_detects_tampering(self):
        batch = self.prepare()["batch_id"]
        with self.assertRaises(ValueError):
            queue_batch(self.store, batch, now=self.now)
        first = Path(self.directory / "media" / self.store.agenda()[0]["filename"])
        original = first.read_bytes()
        first.write_bytes(original + b"changed")
        with self.assertRaises(ValueError):
            queue_batch(self.store, batch, confirmed=True, now=self.now)
        first.write_bytes(original)
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        self.assertEqual({row["state"] for row in self.store.agenda()}, {"queued"})

    def test_reviewed_v5_batch_from_before_rule_binding_remains_valid(self):
        batch = self.prepare()["batch_id"]
        row = self.store.agenda()[0]
        manifest = self.directory / "media" / Path(row["filename"]).with_suffix(".json")
        data = json.loads(manifest.read_text())
        data.pop("rules_hash")
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        with self.store.connect() as connection:
            connection.execute("UPDATE slots SET manifest_hash=? WHERE id=?", (
                hashlib.sha256(manifest.read_bytes()).hexdigest(), row["id"]))
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        self.assertEqual({item["state"] for item in self.store.agenda()}, {"queued"})

    def test_prepare_skips_model_whose_envelope_face_cannot_be_detected(self):
        calls = 0
        def render(raw, phrase_index):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise promotional_story.PreviewError("modelo sem face detectável")
            return fake_render(raw, phrase_index)
        self.render_mock.side_effect = render
        self.prepare()
        rows = self.store.agenda()
        self.assertEqual(len(rows), 10)
        self.assertEqual(self.drive.downloads, 11)
        self.assertNotIn(self.drive.downloaded_ids[0], {row["model_id"] for row in rows})

    def test_rejected_draft_is_removed_and_same_day_can_be_regenerated(self):
        batch = self.prepare()["batch_id"]
        with self.assertRaises(ValueError):
            reject_batch(self.store, batch)
        self.assertTrue(reject_batch(self.store, batch, confirmed=True)["rejected"])
        self.assertEqual(self.store.agenda(), [])
        self.assertFalse(any((self.directory / "media").glob("*.jpg")))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_history").fetchone()[0], 0)
        replacement = self.prepare()
        self.assertTrue(replacement["created"])
        self.assertEqual(replacement["day"], "2026-11-03")

    def test_live_activation_and_three_phase_publish_are_explicit(self):
        batch = self.prepare()["batch_id"]
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        configure_live(self.store, "123456", confirmed=True)
        with self.assertRaises(ValueError):
            enable_live(self.store, now=self.now)
        enable_live(self.store, confirmed=True, now=self.now)
        transport = Transport()
        due = datetime.fromtimestamp(self.store.agenda()[0]["due_at"], ZONE)
        self.assertEqual(tick(self.store, transport, now=due-timedelta(minutes=5))["status"], "staged")
        self.assertEqual(tick(self.store, transport, now=due)["status"], "processing")
        self.assertEqual(tick(self.store, transport, now=due)["status"], "published")
        self.assertEqual(transport.published, 1)

    def test_failed_confirmation_goes_to_review_and_is_not_retried(self):
        batch = self.prepare()["batch_id"]
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        configure_live(self.store, "123456", confirmed=True)
        enable_live(self.store, confirmed=True, now=self.now)
        transport = Transport()
        transport.stage_image = Mock(side_effect=ValueError("secret provider body"))
        due = datetime.fromtimestamp(self.store.agenda()[0]["due_at"], ZONE)
        self.assertEqual(tick(self.store, transport, now=due-timedelta(minutes=5))["status"], "review")
        self.assertEqual(self.store.agenda()[0]["state"], "review")
        self.assertEqual(transport.stage_image.call_count, 1)
        self.assertEqual(tick(self.store, transport, now=due)["status"], "idle")

    def test_retention_removes_only_old_published_promotional_media(self):
        batch = self.prepare()["batch_id"]
        rows = self.store.agenda()
        with self.store.connect() as conn:
            conn.execute("UPDATE slots SET state='published',due_at=? WHERE id=?",
                         (int((self.now-timedelta(days=3)).timestamp()), rows[0]["id"]))
            conn.execute("UPDATE slots SET state='published',due_at=? WHERE id=?",
                         (int((self.now-timedelta(days=1)).timestamp()), rows[1]["id"]))
        old_image = self.directory / "media" / rows[0]["filename"]
        fresh_image = self.directory / "media" / rows[1]["filename"]
        self.assertEqual(cleanup_media(self.store, now=self.now), 2)
        self.assertFalse(old_image.exists())
        self.assertTrue(fresh_image.exists())
        with self.store.connect() as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM slots WHERE batch_id=?", (batch,)).fetchone()[0], 10)


class PromotionalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "promotional"
        http.configure(self.directory, "https://gestao.example")
        self.key = (self.directory / http.KEY_FILE).read_text()
        self.env = {"PATH_INFO": http.PATH, "REQUEST_METHOD": "POST", "HTTP_HOST": "gestao.example",
                    "HTTP_AUTHORIZATION": "Bearer " + self.key, "CONTENT_LENGTH": "0", "QUERY_STRING": ""}

    def test_private_endpoint_is_separate_and_disabled_without_reading_meta(self):
        self.assertNotEqual(http.PATH, "/internal/stories/tick")
        factory = Mock()
        self.assertEqual(http.handle(self.env, self.directory, factory), (200, {"status": "disabled"}))
        factory.assert_not_called()
        for changes, status in [({"HTTP_AUTHORIZATION": ""}, 401), ({"QUERY_STRING": "key=x"}, 400),
                                ({"HTTP_ORIGIN": ""}, 403), ({"REQUEST_METHOD": "GET"}, 405),
                                ({"HTTP_HOST": "evil.example"}, 403), ({"CONTENT_LENGTH": "1"}, 400)]:
            self.assertEqual(http.handle(self.env | changes, self.directory, factory)[0], status)

    def test_key_is_private_and_never_replaced(self):
        before = {path.name: path.read_bytes() for path in self.directory.glob("promotional-stories-*")}
        with self.assertRaises(FileExistsError):
            http.configure(self.directory, "https://gestao.example")
        self.assertEqual({path.name: path.read_bytes() for path in self.directory.glob("promotional-stories-*")}, before)
        self.assertEqual((self.directory / http.KEY_FILE).stat().st_mode & 0o777, 0o600)

    def test_enabled_endpoint_releases_lease_and_throttles_repeated_calls(self):
        store = Store(self.directory)
        with store.connect() as conn:
            conn.execute("UPDATE policy SET enabled=1,account_id='123456' WHERE id=1")
        factory = Mock(return_value=Transport())
        now = datetime(2026, 11, 3, 1, 0, tzinfo=ZONE)
        with patch("promotional_stories.http.tick", return_value={"status": "idle"}) as runner:
            self.assertEqual(http.handle(self.env, self.directory, factory, now=now),
                             (200, {"status": "idle"}))
            self.assertEqual(http.handle(self.env, self.directory, factory,
                                         now=now+timedelta(seconds=10)),
                             (200, {"status": "throttled"}))
        self.assertEqual(runner.call_count, 1)
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT lease_until FROM http_runtime").fetchone()[0], 0)

    def test_idle_publish_tick_advances_daily_generation_without_another_scheduler(self):
        store = Store(self.directory)
        with store.connect() as conn:
            conn.execute("UPDATE policy SET enabled=1,account_id='123456' WHERE id=1")
        factory = Mock(return_value=Transport())
        now = datetime(2026, 11, 3, 1, 0, tzinfo=ZONE)
        with patch("promotional_stories.http.tick", return_value={"status": "idle"}), \
             patch("promotional_stories.http.run_daily_step",
                   return_value={"status": "preparing", "completed": 1, "total": 10}) as daily:
            self.assertEqual(http.handle(self.env, self.directory, factory, now=now),
                             (200, {"status": "preparing"}))
        daily.assert_called_once_with(unittest.mock.ANY, now=now)

    def test_due_publication_takes_priority_over_daily_generation(self):
        store = Store(self.directory)
        with store.connect() as conn:
            conn.execute("UPDATE policy SET enabled=1,account_id='123456' WHERE id=1")
        factory = Mock(return_value=Transport())
        now = datetime(2026, 11, 3, 1, 0, tzinfo=ZONE)
        with patch("promotional_stories.http.tick", return_value={"status": "staged"}), \
             patch("promotional_stories.http.run_daily_step") as daily:
            self.assertEqual(http.handle(self.env, self.directory, factory, now=now),
                             (200, {"status": "staged"}))
        daily.assert_not_called()

    def test_wsgi_delegates_every_existing_route_unchanged(self):
        for path in ("/", "/healthz", "/internal/stories/tick", "/internal/scheduler/tick", "/mcp"):
            env = {"PATH_INFO": path, "REQUEST_METHOD": "POST", "wsgi.input": io.BytesIO(b"original")}
            start = Mock()
            response = [b"existing"]
            with patch("stories.wsgi.application", return_value=response) as existing, \
                 patch("promotional_stories.http.handle") as handler:
                self.assertIs(promo_wsgi.application(env, start), response)
            self.assertIs(existing.call_args.args[0], env)
            self.assertIs(existing.call_args.args[1], start)
            handler.assert_not_called()

    def test_unconfigured_wsgi_fails_closed(self):
        result = {}
        def start(status, headers):
            result.update(status=status, headers=dict(headers))
        with patch.dict(os.environ, {"ARTENOALTAR_PROMOTIONAL_STORIES_DIR": ""}), \
             patch("promotional_stories.wsgi.client_factory") as factory:
            body = b"".join(promo_wsgi.application(self.env, start))
        self.assertTrue(result["status"].startswith("503"))
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        self.assertIn("error", json.loads(body))
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
