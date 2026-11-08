import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from reels import captions
from reels.validator import VideoValidationError, inspect


class Result:
    returncode = 0
    stdout = json.dumps({
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1080,
             "height": 1920, "avg_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "18.5"},
    }).encode()


class ReelsValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video = Path(self.temp.name) / "reel.mp4"
        self.video.write_bytes(b"\0\0\0\x18ftypisomlicensed")

    def test_reads_compatible_video_and_audio_without_modifying_file(self):
        before = self.video.read_bytes()
        calls = []

        def runner(arguments, **options):
            calls.append((arguments, options))
            return Result()

        metadata = inspect(self.video, executable="/usr/bin/ffprobe", runner=runner)
        self.assertEqual(metadata, {"duration": 18.5, "width": 1080, "height": 1920,
                                   "fps": 30.0, "video_codec": "h264",
                                   "audio_codec": "aac", "has_audio": True})
        self.assertEqual(self.video.read_bytes(), before)
        self.assertNotIn("shell", calls[0][1])

    def test_rejects_missing_audio_probe_failure_and_symlink(self):
        payload = Result()
        payload.stdout = json.dumps({"streams": [{"codec_type": "video"}],
                                     "format": {"duration": "10"}}).encode()
        with self.assertRaises(VideoValidationError):
            inspect(self.video, executable="/probe", runner=lambda *args, **kwargs: payload)
        with self.assertRaises(VideoValidationError):
            inspect(self.video, executable="/probe", runner=lambda *args, **kwargs:
                    (_ for _ in ()).throw(subprocess.TimeoutExpired("probe", 20)))
        link = Path(self.temp.name) / "link.mp4"
        link.symlink_to(self.video)
        with self.assertRaises(VideoValidationError):
            inspect(link, executable="/probe", runner=lambda *args, **kwargs: Result())

    def test_caption_rotation_uses_only_approved_catalog(self):
        first = captions.choose("drive-video-123")
        self.assertIn(first, captions.CAPTIONS)
        self.assertEqual(first, captions.choose("drive-video-123"))
        self.assertNotEqual(captions.choose("drive-video-123", 0),
                            captions.choose("drive-video-123", 1))


if __name__ == "__main__":
    unittest.main()
