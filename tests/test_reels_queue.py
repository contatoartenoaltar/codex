from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from reels import queue as queue_module
from reels.queue import (APPLICATION_ID, INITIAL_TIMES, ReelError, Store, ZONE,
                         cancel, claim_due, cleanup_media, configure, enable, finish, import_video,
                         issue_media_grant, pause, resolve_media_grant, schedule,
                         suggest_due, tick)
from reels.meta_client import PublishUncertainError


def fake_mp4(payload=b"licensed-audio"):
    return b"\x00\x00\x00\x18ftypisom" + payload


def metadata(_):
    return {"duration": 18.5, "width": 1080, "height": 1920, "fps": 30,
            "video_codec": "h264", "audio_codec": "aac", "has_audio": True}


class Client:
    media_origin = "https://artenoaltar.pythonanywhere.com"

    def __init__(self, statuses=("FINISHED",), uncertain=False):
        self.statuses = iter(statuses)
        self.uncertain = uncertain
        self.calls = []

    def verify_account(self, account):
        self.calls.append(("verify", account))

    def create_container(self, url, caption, *, share_to_feed):
        self.calls.append(("create", url, caption, share_to_feed))
        return {"id": "800"}

    def container_status(self, container):
        self.calls.append(("status", container))
        return next(self.statuses)

    def publish(self, container):
        self.calls.append(("publish", container))
        if self.uncertain:
            raise PublishUncertainError("resultado incerto")
        return {"id": "900"}


class ReelsQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "reels")
        self.store.initialize()
        self.now = datetime(2026, 11, 9, 8, 0, tzinfo=ZONE)
        self.counter = 0

    def source(self, raw=None, **changes):
        self.counter += 1
        raw = raw or fake_mp4(str(self.counter).encode())
        path = self.root / f"source-{self.counter}.mp4"
        path.write_bytes(raw)
        item = {"id": f"drive_video_{self.counter:04d}", "name": f"Reel {self.counter}.mp4",
                "mimeType": "video/mp4", "size": str(len(raw)),
                "md5Checksum": hashlib.md5(raw, usedforsecurity=False).hexdigest()}
        item.update(changes)
        return item, path, raw

    def imported(self):
        item, path, raw = self.source()
        result = import_video(self.store, item, path, validator=metadata, now=self.now)
        return result["id"], item, path, raw

    def configured(self):
        configure(self.store, "17841436823298466", confirmed=True)

    def test_initializes_an_isolated_disabled_store(self):
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA application_id").fetchone()[0], APPLICATION_ID)
            policy = connection.execute("SELECT * FROM policy").fetchone()
        self.assertEqual((policy["enabled"], policy["mode"], policy["account_id"]), (0, "live", ""))
        self.assertEqual(self.store.path.name, "reels-queue.sqlite3")

    def test_refuses_an_existing_foreign_database(self):
        directory = self.root / "foreign"
        directory.mkdir()
        path = directory / "reels-queue.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE foreign_data(id INTEGER)")
        connection.commit()
        connection.close()
        with self.assertRaises(ReelError):
            Store(directory).initialize()

    def test_import_preserves_exact_bytes_and_is_idempotent(self):
        ident, item, path, raw = self.imported()
        row = self.store.agenda()[0]
        self.assertEqual(row["state"], "ready")
        self.assertEqual((self.store.media / row["filename"]).read_bytes(), raw)
        repeated = import_video(self.store, item, path, validator=metadata, now=self.now)
        self.assertEqual(repeated, {"id": ident, "created": False})
        self.assertEqual(len(self.store.agenda()), 1)

    def test_import_preserves_edits_mov_and_its_extension(self):
        raw = fake_mp4(b"licensed-edits-audio")
        item, path, _ = self.source(raw)
        mov_path = path.with_suffix(".mov")
        path.replace(mov_path)
        item |= {"name": "Reel pronto.mov", "mimeType": "video/quicktime"}
        result = import_video(self.store, item, mov_path, validator=metadata, now=self.now)
        row = self.store.agenda()[0]
        self.assertEqual(row["id"], result["id"])
        self.assertTrue(row["filename"].endswith(".mov"))
        self.assertEqual((self.store.media / row["filename"]).read_bytes(), raw)

    def test_rejects_wrong_type_integrity_and_incompatible_media(self):
        item, path, _ = self.source(mimeType="video/quicktime")
        with self.assertRaises(ReelError):
            import_video(self.store, item, path, validator=metadata, now=self.now)
        item, path, _ = self.source(md5Checksum="0" * 32)
        with self.assertRaises(ReelError):
            import_video(self.store, item, path, validator=metadata, now=self.now)
        item, path, _ = self.source()
        invalid = metadata(path) | {"has_audio": False}
        with self.assertRaises(ReelError):
            import_video(self.store, item, path, validator=lambda _: invalid, now=self.now)
        self.assertEqual(self.store.agenda(), [])

    def test_incompatible_dimensions_are_reported_for_export_diagnosis(self):
        item, path, _ = self.source()
        landscape = metadata(path) | {"width": 1920, "height": 1080}
        with self.assertRaisesRegex(ReelError, "1920 × 1080"):
            import_video(self.store, item, path, validator=lambda _: landscape, now=self.now)

    def test_rejects_replaced_drive_file_with_same_identity(self):
        _, item, _, _ = self.imported()
        replacement = fake_mp4(b"different")
        path = self.root / "replacement.mp4"
        path.write_bytes(replacement)
        changed = item | {"size": str(len(replacement)),
                          "md5Checksum": hashlib.md5(replacement, usedforsecurity=False).hexdigest()}
        with self.assertRaises(ReelError):
            import_video(self.store, changed, path, validator=metadata, now=self.now)

    def test_suggested_schedule_rotates_three_times_and_keeps_one_per_day(self):
        self.configured()
        observed = []
        for index in range(4):
            ident, _, _, _ = self.imported()
            due = suggest_due(self.store, now=self.now)
            observed.append((due.date(), (due.hour, due.minute)))
            schedule(self.store, ident, due, f"Legenda {index}", confirmed=True, now=self.now)
        self.assertEqual([value[1] for value in observed],
                         [INITIAL_TIMES[0], INITIAL_TIMES[1], INITIAL_TIMES[2], INITIAL_TIMES[0]])
        self.assertEqual(len({value[0] for value in observed}), 4)

    def test_adaptive_time_applies_only_to_future_unscheduled_reels(self):
        self.configured()
        first, _, _, _ = self.imported()
        initial = suggest_due(self.store, now=self.now)
        schedule(self.store, first, initial, "Primeiro", confirmed=True, now=self.now)

        second, _, _, _ = self.imported()
        adaptive = suggest_due(self.store, now=self.now, adaptive_time=(14, 30))
        schedule(self.store, second, adaptive, "Segundo", confirmed=True, now=self.now,
                 adaptive_time=(14, 30))

        rows = {row["id"]: row for row in self.store.agenda()}
        self.assertEqual(datetime.fromtimestamp(rows[first]["due_at"], ZONE), initial)
        self.assertEqual((adaptive.hour, adaptive.minute), (14, 30))
        self.assertNotEqual(initial.date(), adaptive.date())

    def test_adaptive_time_is_strict_and_cannot_approve_another_time(self):
        ident, _, _, _ = self.imported()
        self.configured()
        for invalid in ((24, 0), (12, 60), [12, 0], (True, 0), "12:00"):
            with self.subTest(invalid=invalid), self.assertRaises(ReelError):
                suggest_due(self.store, now=self.now, adaptive_time=invalid)
        due = datetime(2026, 11, 9, 14, 0, tzinfo=ZONE)
        with self.assertRaises(ReelError):
            schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now,
                     adaptive_time=(15, 0))

    def test_schedule_requires_configuration_confirmation_and_unique_day(self):
        first, _, _, _ = self.imported()
        second, _, _, _ = self.imported()
        due = datetime(2026, 11, 9, 11, 0, tzinfo=ZONE)
        with self.assertRaises(ReelError):
            schedule(self.store, first, due, "Legenda", confirmed=True, now=self.now)
        self.configured()
        with self.assertRaises(ReelError):
            schedule(self.store, first, due, "Legenda", now=self.now)
        schedule(self.store, first, due, "Legenda", confirmed=True, now=self.now)
        with self.assertRaises(ReelError):
            schedule(self.store, second, due.replace(hour=17), "Outra", confirmed=True, now=self.now)

    def test_cancel_only_before_claim_and_checks_expected_time(self):
        ident, _, _, _ = self.imported()
        self.configured()
        due = suggest_due(self.store, now=self.now)
        receipt = schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now)
        with self.assertRaises(ReelError):
            cancel(self.store, ident, expected_due_at=receipt["due_at"] + 1)
        cancel(self.store, ident, expected_due_at=receipt["due_at"])
        row = self.store.agenda()[0]
        self.assertEqual((row["state"], row["due_at"], row["publication_day"]),
                         ("cancelled", None, None))
        self.assertFalse((self.store.media / row["filename"]).exists())

    def test_disabled_policy_never_claims_due_reel(self):
        ident, _, _, _ = self.imported()
        self.configured()
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now)
        self.assertIsNone(claim_due(self.store, now=due))
        self.assertEqual(self.store.agenda()[0]["state"], "queued")

    def test_claim_is_exactly_once_and_completion_is_idempotency_guarded(self):
        ident, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now)
        results = []
        barrier = threading.Barrier(2)

        def runner():
            barrier.wait()
            results.append(claim_due(self.store, now=due))

        threads = [threading.Thread(target=runner) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        claimed = [item for item in results if item]
        self.assertEqual(len(claimed), 1)
        claim = claimed[0]["claim"]
        self.assertEqual(finish(self.store, ident, claim, remote_id="1789_123", now=due),
                         {"status": "published"})
        with self.assertRaises(ReelError):
            finish(self.store, ident, claim, remote_id="1789_123", now=due)
        self.assertEqual(self.store.agenda()[0]["state"], "published")

    def test_uncertain_result_and_stale_claim_go_to_review_without_retry(self):
        first, _, _, _ = self.imported()
        second, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        first_due = suggest_due(self.store, now=self.now)
        schedule(self.store, first, first_due, "Primeiro", confirmed=True, now=self.now)
        claim = claim_due(self.store, now=first_due)
        finish(self.store, first, claim["claim"], error="Resultado não confirmado", now=first_due)
        self.assertEqual(self.store.agenda()[0]["state"], "review")

        second_due = suggest_due(self.store, now=first_due + timedelta(days=1))
        schedule(self.store, second, second_due, "Segundo", confirmed=True,
                 now=first_due + timedelta(days=1))
        stale = claim_due(self.store, now=second_due)
        self.assertIsNotNone(stale)
        issue_media_grant(self.store, second, stale["claim"], now=second_due)
        self.assertIsNone(claim_due(self.store, now=second_due + timedelta(minutes=11)))
        rows = {row["id"]: row for row in self.store.agenda()}
        self.assertEqual(rows[second]["state"], "review")
        with self.store.connect() as connection:
            attempt = connection.execute(
                "SELECT outcome FROM attempts WHERE reel_id=?", (second,)).fetchone()
            grant = connection.execute(
                "SELECT revoked FROM media_grants WHERE reel_id=?", (second,)).fetchone()
        self.assertEqual(attempt["outcome"], "review")
        self.assertEqual(grant["revoked"], 1)

    def test_processing_item_can_finish_after_thirty_minutes(self):
        ident, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now)
        client = Client(statuses=("FINISHED",))
        self.assertEqual(tick(self.store, client, now=due), {"status": "processing"})
        self.assertEqual(tick(self.store, client, now=due + timedelta(minutes=31)),
                         {"status": "published"})
        self.assertEqual(self.store.agenda()[0]["state"], "published")

    def test_processing_item_over_six_hours_goes_to_review(self):
        ident, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now)
        self.assertEqual(tick(self.store, Client(), now=due), {"status": "processing"})
        self.assertIsNone(claim_due(self.store, now=due + timedelta(hours=6, seconds=1)))
        self.assertEqual(self.store.agenda()[0]["state"], "review")

    def test_pause_stops_new_claims(self):
        ident, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda", confirmed=True, now=self.now)
        pause(self.store)
        self.assertIsNone(claim_due(self.store, now=due))

    def test_operator_cli_keeps_queue_disabled_until_strong_confirmation(self):
        directory = self.root / "operator"
        with redirect_stdout(io.StringIO()):
            queue_module.main(["initialize", "--directory", str(directory)])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            queue_module.main([
                "configure", "--directory", str(directory), "--account-id", "123456",
                "--confirm", "yes",
            ])
        with redirect_stdout(io.StringIO()):
            queue_module.main([
                "configure", "--directory", str(directory), "--account-id", "123456",
                "--confirm", queue_module.CONFIGURE_CONFIRMATION,
            ])
        output = io.StringIO()
        with redirect_stdout(output):
            queue_module.main(["status", "--directory", str(directory)])
        self.assertFalse(json.loads(output.getvalue())["enabled"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            queue_module.main([
                "enable", "--directory", str(directory), "--account-id", "123456",
                "--confirm", "ENABLE",
            ])
        with redirect_stdout(io.StringIO()):
            queue_module.main([
                "enable", "--directory", str(directory), "--account-id", "123456",
                "--confirm", queue_module.ENABLE_CONFIRMATION,
            ])
            queue_module.main(["pause", "--directory", str(directory)])
        self.assertFalse(queue_module.policy_status(Store(directory))["enabled"])

    def test_tick_persists_container_polls_and_publishes_once(self):
        ident, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda aprovada", confirmed=True, now=self.now)
        client = Client(statuses=("IN_PROGRESS", "FINISHED"))

        self.assertEqual(tick(self.store, client, now=due), {"status": "processing"})
        row = self.store.agenda()[0]
        self.assertEqual((row["state"], row["container"], row["claim"]),
                         ("processing", "800", ""))
        create = next(call for call in client.calls if call[0] == "create")
        token = create[1].removeprefix(client.media_origin + "/reels-media/").removesuffix(".mp4")
        self.assertEqual(resolve_media_grant(self.store, token, now=due).filename, row["filename"])

        self.assertEqual(tick(self.store, client, now=due + timedelta(minutes=1)),
                         {"status": "processing"})
        self.assertEqual(tick(self.store, client, now=due + timedelta(minutes=2)),
                         {"status": "published"})
        row = self.store.agenda()[0]
        self.assertEqual((row["state"], row["remote_id"]), ("published", "900"))
        self.assertFalse((self.store.media / row["filename"]).exists())
        self.assertIsNone(resolve_media_grant(self.store, token, now=due))
        self.assertEqual([call[0] for call in client.calls].count("create"), 1)
        self.assertEqual([call[0] for call in client.calls].count("publish"), 1)

    def test_cleanup_removes_only_terminal_media_copies(self):
        published, _, _, _ = self.imported()
        ready, _, _, _ = self.imported()
        with self.store.connect() as connection:
            connection.execute("UPDATE reels SET state='published' WHERE id=?", (published,))
        self.assertEqual(cleanup_media(self.store), 1)
        rows = {row["id"]: row for row in self.store.agenda()}
        self.assertFalse((self.store.media / rows[published]["filename"]).exists())
        self.assertTrue((self.store.media / rows[ready]["filename"]).exists())

    def test_tick_never_retries_uncertain_final_publish(self):
        ident, _, _, _ = self.imported()
        self.configured()
        enable(self.store, "17841436823298466", confirmed=True)
        due = suggest_due(self.store, now=self.now)
        schedule(self.store, ident, due, "Legenda aprovada", confirmed=True, now=self.now)
        client = Client(uncertain=True)
        tick(self.store, client, now=due)
        self.assertEqual(tick(self.store, client, now=due + timedelta(minutes=1)),
                         {"status": "review"})
        self.assertEqual(self.store.agenda()[0]["state"], "review")
        self.assertEqual(tick(self.store, client, now=due + timedelta(minutes=2)),
                         {"status": "idle"})
        self.assertEqual([call[0] for call in client.calls].count("publish"), 1)


if __name__ == "__main__":
    unittest.main()
