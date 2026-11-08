from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reels import automation
from reels.queue import Store, ZONE, cancel, configure, enable, policy_status
import social_schedule


def mp4(label=b"ready"):
    return b"\0\0\0\x18ftypisom" + label


class Client:
    def __init__(self, files):
        self.files = files
        self.raw = {item["id"]: item["raw"] for item in files}

    def catalog(self, root):
        return {"complete": True, "folder_id": root, "files": self.files}

    def download_video(self, item, destination):
        Path(destination).write_bytes(self.raw[item["id"]])


def item(ident, raw):
    return {"id": ident, "name": ident + ".mp4", "mimeType": "video/mp4",
            "size": str(len(raw)), "md5Checksum": hashlib.md5(raw, usedforsecurity=False).hexdigest(),
            "path": [ident + ".mp4"], "raw": raw}


class ReelsAutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "reels")
        self.store.initialize()
        self.drive = self.root / "drive"
        self.drive.mkdir()
        (self.drive / "reels-drive-source.json").write_text(json.dumps({
            "folder_id": "driveFolder12345"
        }))
        self.now = datetime(2026, 11, 9, 8, tzinfo=ZONE)
        configure(self.store, "123456", confirmed=True)
        self.metadata = lambda path: {"duration": 12, "width": 1080, "height": 1920,
                                      "fps": 30, "video_codec": "h264",
                                      "audio_codec": "aac", "has_audio": True}

    def test_disabled_policy_never_reads_drive(self):
        client = Client([])
        client.catalog = lambda root: (_ for _ in ()).throw(AssertionError("Drive lido"))
        self.assertEqual(automation.run(self.store, self.drive, client=client, now=self.now),
                         {"status": "disabled"})

    def test_imports_schedules_one_and_does_not_duplicate(self):
        enable(self.store, "123456", confirmed=True)
        raw = mp4()
        source = item("drive_video_0001", raw)
        result = automation.run(self.store, self.drive, client=Client([source]),
                                media_validator=self.metadata, now=self.now)
        self.assertEqual(result["status"], "queued")
        row = self.store.agenda()[0]
        self.assertEqual(row["state"], "queued")
        self.assertTrue(row["caption"])
        self.assertEqual(automation.run(self.store, self.drive, client=Client([source]),
                                        media_validator=self.metadata, now=self.now)["status"], "idle")

    def test_bad_video_is_remembered_and_next_run_uses_next_valid_video(self):
        enable(self.store, "123456", confirmed=True)
        bad = item("drive_video_0001", mp4(b"bad"))
        good = item("drive_video_0002", mp4(b"good"))

        def validate(path):
            if path.read_bytes().endswith(b"bad"):
                raise ValueError("invalid private detail")
            return self.metadata(path)

        first = automation.run(self.store, self.drive, client=Client([bad, good]),
                               media_validator=validate, now=self.now)
        self.assertEqual(first["status"], "queued")
        self.assertEqual(self.store.agenda()[0]["source_id"], good["id"])
        with self.store.connect() as connection:
            error = connection.execute("SELECT error FROM reel_import_errors").fetchone()[0]
        self.assertIn("invalid", error)
        self.assertEqual(policy_status(self.store)["invalid_files"], 1)

    def test_valid_reel_decision_changes_only_the_next_unscheduled_item(self):
        enable(self.store, "123456", confirmed=True)
        decisions = self.root / "decisions"
        decisions.mkdir()
        social_schedule.save(decisions, {
            "reel": {"state": "selected", "selected_hour": 19},
        }, generated_at=int(self.now.timestamp()))
        source = item("drive_video_0001", mp4())

        result = automation.run(self.store, self.drive, client=Client([source]),
                                media_validator=self.metadata, now=self.now,
                                schedule_directory=decisions)

        row = self.store.agenda()[0]
        self.assertEqual(result["status"], "queued")
        self.assertEqual(datetime.fromtimestamp(row["due_at"], ZONE).hour, 19)

        social_schedule.save(decisions, {
            "reel": {"state": "selected", "selected_hour": 21},
        }, generated_at=int(self.now.timestamp()) + 1)
        unchanged = automation.run(self.store, self.drive, client=Client([source]),
                                   media_validator=self.metadata, now=self.now,
                                   schedule_directory=decisions)
        self.assertEqual(unchanged["status"], "idle")
        self.assertEqual(self.store.agenda()[0]["due_at"], row["due_at"])

    def test_missing_or_public_decision_keeps_initial_rotation(self):
        enable(self.store, "123456", confirmed=True)
        decisions = self.root / "decisions"
        decisions.mkdir()
        decision = decisions / social_schedule.FILENAME
        decision.write_text('{"decisions":{"reel":{"hour":19,"minute":0}}}')
        decision.chmod(0o644)
        source = item("drive_video_0001", mp4())

        automation.run(self.store, self.drive, client=Client([source]),
                       media_validator=self.metadata, now=self.now,
                       schedule_directory=decisions)

        due = datetime.fromtimestamp(self.store.agenda()[0]["due_at"], ZONE)
        self.assertEqual((due.hour, due.minute), (11, 0))

    def test_cancelled_reel_is_not_scheduled_again_automatically(self):
        enable(self.store, "123456", confirmed=True)
        source = item("drive_video_0001", mp4())
        automation.run(self.store, self.drive, client=Client([source]),
                       media_validator=self.metadata, now=self.now)
        row = self.store.agenda()[0]
        cancel(self.store, row["id"], expected_due_at=row["due_at"])

        result = automation.run(self.store, self.drive, client=Client([source]),
                                media_validator=self.metadata, now=self.now)

        self.assertEqual(result["status"], "empty")
        self.assertEqual(self.store.agenda()[0]["state"], "cancelled")

    def test_review_item_blocks_later_automatic_preparation(self):
        enable(self.store, "123456", confirmed=True)
        source = item("drive_video_0001", mp4())
        automation.run(self.store, self.drive, client=Client([source]),
                       media_validator=self.metadata, now=self.now)
        with self.store.connect() as connection:
            connection.execute("UPDATE reels SET state='review' WHERE source_id=?", (source["id"],))
        later = item("drive_video_0002", mp4(b"later"))

        result = automation.run(self.store, self.drive, client=Client([source, later]),
                                media_validator=self.metadata, now=self.now)

        self.assertEqual(result, {"status": "review"})
        self.assertEqual(len(self.store.agenda()), 1)

    def test_corrected_drive_file_clears_its_previous_import_warning(self):
        enable(self.store, "123456", confirmed=True)
        bad = item("drive_video_0001", mp4(b"bad"))
        self.assertEqual(automation.run(
            self.store, self.drive, client=Client([bad]),
            media_validator=lambda path: (_ for _ in ()).throw(ValueError("invalid")),
            now=self.now), {"status": "review"})
        self.assertEqual(policy_status(self.store)["invalid_files"], 1)

        corrected = item("drive_video_0001", mp4(b"corrected"))
        result = automation.run(self.store, self.drive, client=Client([corrected]),
                                media_validator=self.metadata, now=self.now)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(policy_status(self.store)["invalid_files"], 0)


if __name__ == "__main__":
    unittest.main()
