from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reels import automation
from reels.queue import Store, ZONE, cancel, configure, enable, policy_status
import feed_composer
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


def item(ident, raw, *, suffix=".mp4", mime="video/mp4"):
    return {"id": ident, "name": ident + suffix, "mimeType": mime,
            "size": str(len(raw)), "md5Checksum": hashlib.md5(raw, usedforsecurity=False).hexdigest(),
            "path": [ident + suffix], "raw": raw}


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

    def test_preflight_validates_real_bytes_without_importing_or_scheduling(self):
        raw = mp4(b"preflight")
        source = item("drive_video_0001", raw)

        result = automation.preflight(
            self.drive, client=Client([source]), media_validator=self.metadata)

        self.assertEqual(result, {
            "status": "ready", "file_name": "drive_video_0001.mp4",
            "bytes": len(raw), "duration_seconds": 12.0, "width": 1080,
            "height": 1920, "fps": 30.0, "publishing_enabled": False,
        })
        self.assertEqual(self.store.agenda(), [])
        self.assertEqual(list(self.drive.glob(".reel-preflight-*")), [])

    def test_preflight_accepts_edits_mov_without_importing(self):
        raw = mp4(b"edits-mov")
        source = item("drive_video_0002", raw, suffix=".mov", mime="video/quicktime")
        result = automation.preflight(
            self.drive, client=Client([source]), media_validator=self.metadata)
        self.assertEqual(result["file_name"], "drive_video_0002.mov")
        self.assertFalse(result["publishing_enabled"])
        self.assertEqual(self.store.agenda(), [])
        self.assertEqual(list(self.drive.glob(".reel-preflight-*")), [])

    def test_manual_analysis_marks_video_ready_without_scheduling_or_publishing(self):
        source = item("drive_video_0003", mp4(b"manual-analysis"))

        result = automation.analyze_next(
            self.store, self.drive, client=Client([source]),
            media_validator=self.metadata, now=self.now)

        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["file"], source["name"])
        row = self.store.agenda()[0]
        self.assertEqual(row["state"], "ready")
        self.assertIsNone(row["due_at"])
        self.assertEqual(row["remote_id"], "")

    def test_temporary_cleanup_failure_does_not_reject_valid_manual_analysis(self):
        source = item("drive_video_0007", mp4(b"cleanup-busy"))

        with patch("reels.automation._discard_staging") as discard:
            result = automation.analyze_next(
                self.store, self.drive, client=Client([source]),
                media_validator=self.metadata, now=self.now)

        self.assertEqual(result["status"], "eligible")
        self.assertEqual(self.store.agenda()[0]["state"], "ready")
        self.assertEqual(policy_status(self.store)["invalid_files"], 0)
        discard.assert_called_once()

    def test_manual_analysis_reports_safe_error_and_remembers_file_name(self):
        source = item("drive_video_0004", mp4(b"manual-bad"))

        result = automation.analyze_next(
            self.store, self.drive, client=Client([source]),
            media_validator=lambda path: (_ for _ in ()).throw(
                ValueError("private /server/path detail")), now=self.now)

        self.assertEqual(result["status"], "incompatible")
        self.assertEqual(result["file"], source["name"])
        self.assertNotIn("/server/path", result["error"])
        details = policy_status(self.store)["invalid_file_details"]
        self.assertEqual(details[0]["file"], source["name"])
        self.assertEqual(self.store.agenda(), [])

    def test_manual_analysis_retries_same_rejected_file_after_operational_fix(self):
        source = item("drive_video_0006", mp4(b"retry-after-fix"))
        failed = automation.analyze_next(
            self.store, self.drive, client=Client([source]),
            media_validator=lambda path: (_ for _ in ()).throw(
                ValueError("Não foi possível baixar o vídeo do Drive. O arquivo de origem foi preservado.")),
            now=self.now)
        self.assertEqual(failed["status"], "incompatible")

        retried = automation.analyze_next(
            self.store, self.drive, client=Client([source]),
            media_validator=self.metadata, now=self.now)

        self.assertEqual(retried["status"], "eligible")
        self.assertEqual(policy_status(self.store)["invalid_files"], 0)

    def test_manual_analysis_skips_files_already_checked(self):
        source = item("drive_video_0005", mp4(b"already-ready"))
        automation.analyze_next(self.store, self.drive, client=Client([source]),
                                media_validator=self.metadata, now=self.now)

        result = automation.analyze_next(
            self.store, self.drive, client=Client([source]),
            media_validator=lambda path: (_ for _ in ()).throw(AssertionError("validated twice")),
            now=self.now)

        self.assertEqual(result, {"status": "up_to_date", "checked": 0})

    def test_manual_analysis_clears_stale_error_for_already_imported_file(self):
        source = item("drive_video_0008", mp4(b"imported-before-cleanup-error"))
        automation.analyze_next(self.store, self.drive, client=Client([source]),
                                media_validator=self.metadata, now=self.now)
        with self.store.connect() as connection:
            automation._remember_error(
                connection, source,
                OSError(16, "Device or resource busy", ".reel-analysis-old"))
        self.assertEqual(policy_status(self.store)["invalid_files"], 1)

        result = automation.analyze_next(
            self.store, self.drive, client=Client([source]),
            media_validator=self.metadata, now=self.now)

        self.assertEqual(result, {"status": "up_to_date", "checked": 0})
        self.assertEqual(policy_status(self.store)["invalid_files"], 0)

    def test_preflight_removes_file_when_validation_fails(self):
        raw = mp4(b"invalid")
        source = item("drive_video_0003", raw)
        with self.assertRaisesRegex(ValueError, "invalid metadata"):
            automation.preflight(
                self.drive, client=Client([source]),
                media_validator=lambda _: (_ for _ in ()).throw(
                    ValueError("invalid metadata")))
        self.assertEqual(list(self.drive.glob(".reel-preflight-*")), [])

    def test_imports_schedules_one_and_does_not_duplicate(self):
        enable(self.store, "123456", confirmed=True)
        raw = mp4()
        source = item("drive_video_0001", raw)
        result = automation.run(self.store, self.drive, client=Client([source]),
                                media_validator=self.metadata, now=self.now)
        self.assertEqual(result["status"], "queued")
        row = self.store.agenda()[0]
        self.assertEqual(row["state"], "queued")
        self.assertEqual(row["caption"], feed_composer.standard_caption())
        self.assertEqual(automation.run(self.store, self.drive, client=Client([source]),
                                        media_validator=self.metadata, now=self.now)["status"], "idle")

    def test_feed_caption_can_update_existing_untouched_queued_reel_without_rescheduling(self):
        enable(self.store, "123456", confirmed=True)
        source = item("drive_video_0001", mp4())
        automation.run(self.store, self.drive, client=Client([source]),
                       media_validator=self.metadata, now=self.now)
        before = self.store.agenda()[0]
        with self.store.connect() as connection:
            connection.execute("UPDATE reels SET caption='Legenda antiga' WHERE id=?", (before["id"],))

        result = automation.apply_feed_caption(self.store)

        after = self.store.agenda()[0]
        self.assertEqual(result, {
            "updated": 1, "caption_length": len(feed_composer.standard_caption())})
        self.assertEqual(after["caption"], feed_composer.standard_caption())
        self.assertEqual(after["due_at"], before["due_at"])
        self.assertEqual(after["state"], "queued")

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
            source_name = connection.execute(
                "SELECT source_name FROM reel_import_error_names").fetchone()[0]
        self.assertIn("invalid", error)
        self.assertEqual(source_name, bad["name"])
        self.assertEqual(policy_status(self.store)["invalid_files"], 1)
        self.assertEqual(policy_status(self.store)["invalid_file_details"][0]["file"], bad["name"])
        self.assertNotIn("private", policy_status(self.store)["invalid_file_details"][0]["error"])

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

    def test_deleted_bad_video_is_forgotten_and_replacement_may_have_another_name(self):
        enable(self.store, "123456", confirmed=True)
        bad = item("drive_video_0001", mp4(b"bad"))
        self.assertEqual(automation.run(
            self.store, self.drive, client=Client([bad]),
            media_validator=lambda path: (_ for _ in ()).throw(ValueError("invalid")),
            now=self.now), {"status": "review"})
        self.assertEqual(policy_status(self.store)["invalid_files"], 1)

        replacement = item("drive_video_9999", mp4(b"corrected")) | {
            "name": "novo-video-corrigido.mp4",
        }
        result = automation.run(self.store, self.drive, client=Client([replacement]),
                                media_validator=self.metadata, now=self.now)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(self.store.agenda()[0]["source_name"], "novo-video-corrigido.mp4")
        self.assertEqual(policy_status(self.store)["invalid_files"], 0)

    def test_deleted_bad_video_clears_warning_even_without_replacement(self):
        enable(self.store, "123456", confirmed=True)
        bad = item("drive_video_0001", mp4(b"bad"))
        automation.run(
            self.store, self.drive, client=Client([bad]),
            media_validator=lambda path: (_ for _ in ()).throw(ValueError("invalid")),
            now=self.now)

        self.assertEqual(automation.run(
            self.store, self.drive, client=Client([]),
            media_validator=self.metadata, now=self.now), {"status": "empty"})
        self.assertEqual(policy_status(self.store)["invalid_files"], 0)


if __name__ == "__main__":
    unittest.main()
