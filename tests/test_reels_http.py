from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from reels import http
from reels import media
from reels import wsgi as reels_wsgi
from reels.queue import Store, import_video, issue_media_grant


ZONE = http.ZONE


class ReelsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "reels"
        http.configure(self.directory, "https://gestao.example")
        self.key = (self.directory / http.KEY_FILE).read_text()
        self.store = Store(self.directory)
        self.now = datetime(2026, 11, 9, 10, tzinfo=ZONE)
        self.factory = Mock(return_value=object())
        self.environment = {
            "PATH_INFO": http.PATH, "REQUEST_METHOD": "POST", "HTTP_HOST": "gestao.example",
            "HTTP_AUTHORIZATION": "Bearer " + self.key, "CONTENT_LENGTH": "0", "QUERY_STRING": "",
        }

    def call(self, changes=None, *, now=None):
        return http.handle(self.environment | (changes or {}), self.directory, self.factory,
                           now=now or self.now)

    def enable_live(self):
        with self.store.connect() as connection:
            connection.execute("UPDATE policy SET enabled=1,mode='live',account_id='123456' WHERE id=1")

    def test_invalid_requests_never_construct_client(self):
        cases = [
            ({"HTTP_AUTHORIZATION": ""}, 401), ({"QUERY_STRING": "secret=x"}, 400),
            ({"HTTP_ORIGIN": ""}, 403), ({"REQUEST_METHOD": "GET"}, 405),
            ({"HTTP_HOST": "evil.example"}, 403), ({"CONTENT_LENGTH": "1"}, 400),
            ({"HTTP_TRANSFER_ENCODING": "chunked"}, 400),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.call(changes)[0], expected)
        self.factory.assert_not_called()

    def test_disabled_policy_never_reads_meta_credentials(self):
        self.assertEqual(self.call(), (200, {"status": "disabled"}))
        self.factory.assert_not_called()

    def test_configure_is_private_and_never_overwrites(self):
        protected = [self.directory / http.KEY_FILE, self.directory / http.CONFIG_FILE]
        before = {path.name: path.read_bytes() for path in protected}
        with self.assertRaises(FileExistsError):
            http.configure(self.directory, "https://gestao.example")
        self.assertEqual({path.name: path.read_bytes() for path in protected}, before)
        self.assertEqual((self.directory / http.KEY_FILE).stat().st_mode & 0o777, 0o600)
        (self.directory / http.CONFIG_FILE).chmod(0o644)
        self.assertEqual(self.call()[0], 503)

    def test_operator_cli_configures_and_reports_status_without_exposing_key(self):
        directory = Path(self.temp.name) / "operator-trigger"
        output = io.StringIO()
        with redirect_stdout(output):
            http.main([
                "configure", "--directory", str(directory),
                "--origin", "https://gestao.example",
            ])
        self.assertIn("Publishing remains disabled", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            http.main(["status", "--directory", str(directory)])
        result = json.loads(output.getvalue())
        self.assertEqual(result, {
            "configured": True,
            "origin": "https://gestao.example",
            "publishing_enabled": False,
        })
        self.assertNotIn((directory / http.KEY_FILE).read_text(), output.getvalue())

    def test_live_calls_are_throttled_and_release_the_lease(self):
        self.enable_live()
        with patch("reels.http.tick", return_value={"status": "idle"}) as runner:
            self.assertEqual(self.call(), (200, {"status": "idle"}))
            self.assertEqual(self.call(now=self.now + timedelta(seconds=10)),
                             (200, {"status": "throttled"}))
            self.assertEqual(self.call(now=self.now + timedelta(seconds=31)),
                             (200, {"status": "idle"}))
        self.assertEqual(runner.call_count, 2)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute(
                "SELECT lease_until FROM reels_http_runtime").fetchone()[0], 0)

    def test_idle_live_tick_may_prepare_one_reel_without_coupling_other_queues(self):
        self.enable_live()
        preparer = Mock(return_value={"status": "queued"})
        with patch("reels.http.tick", return_value={"status": "idle"}):
            self.assertEqual(http.handle(self.environment, self.directory, self.factory,
                                         preparer, now=self.now),
                             (200, {"status": "queued"}))
        self.assertEqual(preparer.call_count, 1)
        self.assertEqual(preparer.call_args.args[0].directory, self.store.directory)
        self.assertEqual(preparer.call_args.kwargs["now"], self.now)

    def test_parallel_calls_use_one_lease(self):
        self.enable_live()
        entered, release = threading.Event(), threading.Event()

        def blocked(store, client, *, now=None):
            entered.set()
            if not release.wait(10):
                raise AssertionError("Teste não liberou a fila")
            return {"status": "idle"}

        with patch("reels.http.tick", side_effect=blocked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.call)
                self.assertTrue(entered.wait(10))
                try:
                    self.assertEqual(self.call(), (200, {"status": "busy"}))
                finally:
                    release.set()
                self.assertEqual(first.result(), (200, {"status": "idle"}))
        self.assertEqual(self.factory.call_count, 1)

    def test_client_failure_is_sanitized_and_releases_lease(self):
        self.enable_live()
        self.factory.side_effect = ValueError("private-meta-token")
        status, result = self.call()
        self.assertEqual(status, 503)
        self.assertNotIn("private-meta-token", str(result))
        with self.store.connect() as connection:
            self.assertEqual(connection.execute(
                "SELECT lease_until FROM reels_http_runtime").fetchone()[0], 0)

    def test_wrapper_delegates_all_other_routes_untouched(self):
        for path in ("/", "/healthz", "/api/state", "/internal/scheduler/tick",
                     "/internal/carousels/tick", "/media/a.jpg", "/mcp"):
            environment = {"PATH_INFO": path, "REQUEST_METHOD": "POST",
                           "wsgi.input": io.BytesIO(b"original")}
            expected = [b"existing-response"]
            start = Mock()
            with patch("carousel_posts.wsgi.application", return_value=expected) as existing, \
                    patch("reels.http.handle") as handler:
                self.assertIs(reels_wsgi.application(environment, start), expected)
            self.assertIs(existing.call_args.args[0], environment)
            self.assertIs(existing.call_args.args[1], start)
            handler.assert_not_called()

    def test_wrapper_serves_only_active_temporary_reel_grant(self):
        raw = b"\0\0\0\x18ftypisomlicensed-audio"
        source = Path(self.temp.name) / "source.mp4"
        source.write_bytes(raw)
        import hashlib
        item = {"id": "drive_video_0001", "name": "Reel.mp4", "mimeType": "video/mp4",
                "size": str(len(raw)),
                "md5Checksum": hashlib.md5(raw, usedforsecurity=False).hexdigest()}
        metadata = lambda path: {"duration": 10, "width": 1080, "height": 1920, "fps": 30,
                                 "video_codec": "h264", "audio_codec": "aac", "has_audio": True}
        ident = import_video(self.store, item, source, validator=metadata, now=self.now)["id"]
        with self.store.connect() as connection:
            connection.execute("UPDATE reels SET state='processing',claim='claim' WHERE id=?", (ident,))
        token = issue_media_grant(self.store, ident, "claim", now=self.now)
        response = {}
        environment = {"PATH_INFO": media.url_path(token), "REQUEST_METHOD": "GET",
                       "QUERY_STRING": "", "wsgi.input": io.BytesIO()}
        with patch.dict(os.environ, {"ARTENOALTAR_REELS_DIR": str(self.directory)}):
            body = b"".join(reels_wsgi.application(
                environment, lambda status, headers: response.update(status=status, headers=dict(headers))))
        self.assertTrue(response["status"].startswith("200"))
        self.assertEqual(response["headers"]["Content-Type"], "video/mp4")
        self.assertEqual(body, raw)

    def test_unconfigured_wrapper_fails_closed(self):
        response = {}

        def start(status, headers):
            response.update(status=status, headers=dict(headers))

        with patch.dict(os.environ, {"ARTENOALTAR_REELS_DIR": ""}), \
                patch("reels.wsgi.client_factory") as factory:
            content = b"".join(reels_wsgi.application(self.environment, start))
        self.assertTrue(response["status"].startswith("503"))
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")
        self.assertIn("error", json.loads(content))
        factory.assert_not_called()

    def test_client_factory_uses_existing_meta_directory_and_public_origin(self):
        meta_directory = Path(self.temp.name) / "meta"
        meta_directory.mkdir()
        with patch.dict(os.environ, {
                "ARTENOALTAR_REELS_META_DIR": str(meta_directory),
                "ARTENOALTAR_ORIGIN": "https://gestao.example",
        }), patch("reels.meta_client.MetaClient.from_directory", return_value=object()) as build:
            reels_wsgi.client_factory("123456")
        build.assert_called_once_with(meta_directory, "123456", "https://gestao.example")

    def test_preparer_shares_only_the_private_schedule_directory(self):
        drive_directory = Path(self.temp.name) / "drive"
        meta_directory = Path(self.temp.name) / "meta"
        drive_directory.mkdir()
        meta_directory.mkdir()
        with patch.dict(os.environ, {
                "ARTENOALTAR_REELS_DRIVE_DIR": str(drive_directory),
                "ARTENOALTAR_REELS_META_DIR": str(meta_directory),
        }), patch("reels.automation.run", return_value={"status": "empty"}) as runner:
            self.assertEqual(reels_wsgi.prepare_reel(self.store, now=self.now),
                             {"status": "empty"})
        runner.assert_called_once_with(self.store, drive_directory,
                                       schedule_directory=str(meta_directory), now=self.now)


if __name__ == "__main__":
    unittest.main()
