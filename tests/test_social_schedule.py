from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import social_schedule
from carousel_posts import queue as carousel


class SocialScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_saves_private_selected_decisions_and_preserves_fallbacks(self):
        social_schedule.save(self.directory, {
            "feed": {"state": "selected", "selected_hour": 18},
            "story": {"state": "learning", "selected_hour": None},
        }, generated_at=123)
        path = self.directory / social_schedule.FILENAME
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(social_schedule.selected(self.directory, "feed", (12, 0)), (18, 0))
        self.assertEqual(social_schedule.selected(self.directory, "story", (7, 30)), (7, 30))
        self.assertNotIn("story", json.loads(path.read_text())["decisions"])

    def test_invalid_or_public_file_cannot_change_schedule(self):
        path = self.directory / social_schedule.FILENAME
        path.write_text('{"decisions":{"feed":{"hour":23,"minute":0}}}')
        path.chmod(0o644)
        self.assertEqual(social_schedule.selected(self.directory, "feed", (12, 0)), (12, 0))
        path.unlink()
        path.symlink_to(self.directory / "missing")
        self.assertEqual(social_schedule.selected(self.directory, "feed", (12, 0)), (12, 0))

    def test_carousel_uses_selected_hour_only_after_a_decision_exists(self):
        now = datetime(2026, 11, 5, 8, 0, tzinfo=carousel.ZONE)
        with patch.dict(os.environ, {"ARTENOALTAR_CAROUSELS_META_DIR": str(self.directory)}):
            self.assertEqual(carousel._next_dates(now, 1)[0].hour, 12)
            social_schedule.save(self.directory, {
                "carousel": {"state": "selected", "selected_hour": 19},
            }, generated_at=int(now.timestamp()))
            self.assertEqual(carousel._next_dates(now, 1)[0].hour, 19)


if __name__ == "__main__":
    unittest.main()
