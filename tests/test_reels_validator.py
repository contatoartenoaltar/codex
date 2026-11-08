import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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

    def test_reads_standard_mp4_without_ffprobe(self):
        def box(kind, payload):
            return (len(payload) + 8).to_bytes(4, "big") + kind + payload

        def media_header(timescale, duration):
            return b"\0" * 12 + timescale.to_bytes(4, "big") + duration.to_bytes(4, "big")

        def track(handler, timescale, duration, sample_entry, timing=b"", tkhd=b""):
            hdlr = box(b"hdlr", b"\0" * 8 + handler)
            mdhd = box(b"mdhd", media_header(timescale, duration))
            stsd = box(b"stsd", b"\0" * 4 + (1).to_bytes(4, "big") + sample_entry)
            stbl = box(b"stbl", stsd + timing)
            return box(b"trak", tkhd + box(b"mdia", mdhd + hdlr + box(b"minf", stbl)))

        ftyp = box(b"ftyp", b"isom\0\0\0\0isom")
        mvhd = box(b"mvhd", media_header(1000, 18500))
        avc1 = box(b"avc1", b"\0" * 24 + (1080).to_bytes(2, "big") +
                   (1920).to_bytes(2, "big"))
        stts = box(b"stts", b"\0" * 4 + (1).to_bytes(4, "big") +
                   (555).to_bytes(4, "big") + (1000).to_bytes(4, "big"))
        video = track(b"vide", 30000, 555000, avc1, stts)
        audio = track(b"soun", 48000, 888000, box(b"mp4a", b"\0" * 8))
        self.video.write_bytes(ftyp + box(b"moov", mvhd + video + audio))
        before = self.video.read_bytes()

        with patch("reels.validator.shutil.which", return_value=None):
            metadata = inspect(self.video)

        self.assertEqual(metadata, {"duration": 18.5, "width": 1080, "height": 1920,
                                   "fps": 30.0, "video_codec": "h264",
                                   "audio_codec": "aac", "has_audio": True})
        self.assertEqual(self.video.read_bytes(), before)

        rotate_90 = (
            (0).to_bytes(4, "big", signed=True) +
            (65536).to_bytes(4, "big", signed=True) +
            (0).to_bytes(4, "big", signed=True) +
            (-65536).to_bytes(4, "big", signed=True) +
            (0).to_bytes(4, "big", signed=True) +
            (0).to_bytes(4, "big", signed=True) +
            (0).to_bytes(4, "big", signed=True) +
            (0).to_bytes(4, "big", signed=True) +
            (1 << 30).to_bytes(4, "big", signed=True)
        )
        tkhd = box(b"tkhd", b"\0" * 40 + rotate_90 + b"\0" * 8)
        landscape = box(b"avc1", b"\0" * 24 + (1920).to_bytes(2, "big") +
                        (1080).to_bytes(2, "big"))
        video = track(b"vide", 30000, 555000, landscape, stts, tkhd)
        self.video.write_bytes(ftyp + box(b"moov", mvhd + video + audio))
        with patch("reels.validator.shutil.which", return_value=None):
            rotated = inspect(self.video)
        self.assertEqual((rotated["width"], rotated["height"]), (1080, 1920))

    def test_fallback_rejects_malformed_or_audio_free_mp4(self):
        malformed = b"\0\0\0\x18ftypisom" + b"\0\0\0\x08moov"
        self.video.write_bytes(malformed)
        with patch("reels.validator.shutil.which", return_value=None), \
                self.assertRaises(VideoValidationError):
            inspect(self.video)

    def test_caption_rotation_uses_only_approved_catalog(self):
        first = captions.choose("drive-video-123")
        self.assertIn(first, captions.CAPTIONS)
        self.assertEqual(first, captions.choose("drive-video-123"))
        self.assertNotEqual(captions.choose("drive-video-123", 0),
                            captions.choose("drive-video-123", 1))


if __name__ == "__main__":
    unittest.main()
