import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reels.media import MediaGrant, issue_token, serve, url_path


class ReelsMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve() / "reels"
        (self.directory / "media").mkdir(parents=True)
        self.filename = "a" * 32 + ".mp4"
        self.payload = b"\x00\x00\x00\x18ftypmp42" + bytes(range(64))
        (self.directory / "media" / self.filename).write_bytes(self.payload)
        self.token = issue_token()
        self.grant = MediaGrant(self.filename, expires_at=2000)

    def call(self, changes=None, *, resolver=None, now=1000):
        result = {}

        def start(status, headers):
            result["status"] = status
            result["headers"] = dict(headers)

        environ = {"PATH_INFO": url_path(self.token), "REQUEST_METHOD": "GET", "QUERY_STRING": ""}
        body = serve(environ | (changes or {}), start, self.directory,
                     resolver or (lambda token: self.grant if token == self.token else None), now=now)
        result["body"] = b"".join(body)
        if hasattr(body, "close"):
            body.close()
        return result

    def test_full_get_and_head_have_video_headers(self):
        result = self.call()
        self.assertTrue(result["status"].startswith("200"))
        self.assertEqual(result["body"], self.payload)
        self.assertEqual(result["headers"]["Content-Type"], "video/mp4")
        self.assertEqual(result["headers"]["Content-Length"], str(len(self.payload)))
        self.assertEqual(result["headers"]["Accept-Ranges"], "bytes")
        self.assertEqual(result["headers"]["Cache-Control"], "no-store, max-age=0")

        head = self.call({"REQUEST_METHOD": "HEAD"})
        self.assertTrue(head["status"].startswith("200"))
        self.assertEqual(head["body"], b"")
        self.assertEqual(head["headers"]["Content-Length"], str(len(self.payload)))

    def test_single_ranges_and_suffix_are_supported(self):
        for value, expected, header in [
            ("bytes=4-11", self.payload[4:12], f"bytes 4-11/{len(self.payload)}"),
            ("bytes=12-", self.payload[12:], f"bytes 12-{len(self.payload)-1}/{len(self.payload)}"),
            ("bytes=-7", self.payload[-7:], f"bytes {len(self.payload)-7}-{len(self.payload)-1}/{len(self.payload)}"),
        ]:
            with self.subTest(value=value):
                result = self.call({"HTTP_RANGE": value})
                self.assertTrue(result["status"].startswith("206"))
                self.assertEqual(result["body"], expected)
                self.assertEqual(result["headers"]["Content-Range"], header)
                self.assertEqual(result["headers"]["Content-Length"], str(len(expected)))

    def test_invalid_or_multiple_range_returns_416_without_bytes(self):
        for value in ("items=0-1", "bytes=0-1,4-5", "bytes=999-", "bytes=9-2", "bytes=-0"):
            with self.subTest(value=value):
                result = self.call({"HTTP_RANGE": value})
                self.assertTrue(result["status"].startswith("416"))
                self.assertEqual(result["body"], b"")
                self.assertEqual(result["headers"]["Content-Range"], f"bytes */{len(self.payload)}")

    def test_tokens_are_opaque_strong_and_validated(self):
        values = {issue_token() for _ in range(40)}
        self.assertEqual(len(values), 40)
        self.assertTrue(all(len(value) >= 43 for value in values))
        with self.assertRaises(ValueError):
            url_path("../" + "a" * 48)
        self.assertTrue(url_path(self.token).endswith(".mp4"))

    def test_unknown_expired_revoked_and_malformed_grants_are_indistinguishable(self):
        cases = [
            lambda _: None,
            lambda _: MediaGrant(self.filename, expires_at=999),
            lambda _: MediaGrant(self.filename, expires_at=2000, revoked=True),
            lambda _: MediaGrant("../secret.mp4", expires_at=2000),
            lambda _: (_ for _ in ()).throw(RuntimeError("private database detail")),
        ]
        for resolver in cases:
            with self.subTest(resolver=resolver):
                result = self.call(resolver=resolver)
                self.assertTrue(result["status"].startswith("404"))
                self.assertEqual(result["body"], b"Not found")

    def test_query_origin_wrong_method_and_bad_path_are_rejected_before_resolution(self):
        calls = []

        def resolver(token):
            calls.append(token)
            return self.grant

        for changes, status in [
            ({"QUERY_STRING": "token=secret"}, "400"),
            ({"HTTP_ORIGIN": "https://evil.example"}, "403"),
            ({"REQUEST_METHOD": "POST"}, "405"),
            ({"PATH_INFO": "/internal/reels/media/../secret.mp4"}, "404"),
            ({"PATH_INFO": "/internal/reels/media/"}, "404"),
        ]:
            with self.subTest(changes=changes):
                self.assertTrue(self.call(changes, resolver=resolver)["status"].startswith(status))
        self.assertEqual(calls, [])

    def test_symlink_hardlink_invalid_mp4_empty_and_oversized_are_not_served(self):
        target = self.directory / "media" / self.filename
        alternate = self.directory / "media" / ("b" * 32 + ".mp4")
        alternate.write_bytes(self.payload)
        os.link(alternate, target.with_name("c" * 32 + ".mp4"))
        cases = [
            ("b" * 32 + ".mp4", b"not-an-mp4"),
            ("d" * 32 + ".mp4", b""),
        ]
        for name, value in cases:
            (self.directory / "media" / name).write_bytes(value)
            result = self.call(resolver=lambda _, name=name: MediaGrant(name, 2000))
            self.assertTrue(result["status"].startswith("404"))
        hard = self.call(resolver=lambda _: MediaGrant("c" * 32 + ".mp4", 2000))
        self.assertTrue(hard["status"].startswith("404"))
        link = self.directory / "media" / ("e" * 32 + ".mp4")
        link.symlink_to(target)
        linked = self.call(resolver=lambda _: MediaGrant(link.name, 2000))
        self.assertTrue(linked["status"].startswith("404"))
        with patch("reels.media.MAX_VIDEO", len(self.payload) - 1):
            oversized = self.call()
        self.assertTrue(oversized["status"].startswith("404"))


if __name__ == "__main__":
    unittest.main()
