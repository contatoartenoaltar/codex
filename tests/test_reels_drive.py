from contextlib import redirect_stdout
import errno
import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import drive_source
from reels import drive


def mp4(payload=b"video-data"):
    return b"\x00\x00\x00\x18ftypisom" + payload


def item(raw, **changes):
    value = {
        "id": "videoIdentifier123",
        "name": "reel-pronto.mp4",
        "mimeType": "video/mp4",
        "size": str(len(raw)),
        "md5Checksum": hashlib.md5(raw, usedforsecurity=False).hexdigest(),
        "modifiedTime": "2026-11-08T12:00:00Z",
        "path": ["reel-pronto.mp4"],
    }
    value.update(changes)
    return value


class Credential:
    def __init__(self):
        self.calls = []

    def before_request(self, transport, method, url, headers):
        self.calls.append((method, url, dict(headers)))
        headers["Authorization"] = "Bearer private-token"


class Response:
    def __init__(self, raw):
        self.stream = io.BytesIO(raw)

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RangeResponse(Response):
    status = 206

    def __init__(self, raw, content_range):
        super().__init__(raw)
        self.headers = {"Content-Range": content_range}


class Opener:
    def __init__(self, raw):
        self.raw = raw
        self.requests = []

    def open(self, request, timeout=0):
        self.requests.append((request, timeout))
        return Response(self.raw)


class CatalogClient:
    def __init__(self, result):
        self.result = result
        self.roots = []

    def catalog(self, root):
        self.roots.append(root)
        return self.result


class ReelDriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def configured(self, folder="folderIdentifier123"):
        (self.directory / drive.CONFIG_FILE).write_text(json.dumps({
            "provider": "google_drive", "folder_id": folder,
        }))
        return folder

    def test_catalog_returns_only_strict_mp4_without_mutating_drive(self):
        folder = self.configured()
        raw = mp4()
        source = {
            "complete": True, "folder_id": folder, "folder_name": "Reels",
            "checked_at": "2026-11-08T12:00:00Z",
            "files": [item(raw), {
                "id": "imageIdentifier12", "name": "capa.jpg", "mimeType": "image/jpeg",
            }, {
                "id": "shortcutIdent123", "name": "atalho",
                "mimeType": drive_source.SHORTCUT_MIME,
            }],
        }
        client = CatalogClient(source)
        result = drive.catalog(self.directory, client)
        self.assertEqual(client.roots, [folder])
        self.assertEqual(result["total_videos"], 1)
        self.assertEqual(result["skipped_non_video"], 2)
        self.assertEqual(result["files"][0]["id"], "videoIdentifier123")

    def test_catalog_and_download_accept_edits_mov_without_conversion(self):
        folder = self.configured()
        raw = mp4(b"quicktime-video")
        metadata = item(raw, name="reel-edits.mov", mimeType="video/quicktime",
                        path=["reel-edits.mov"])
        result = drive.catalog(self.directory, CatalogClient({
            "complete": True, "folder_id": folder, "files": [metadata],
        }))
        self.assertEqual(result["files"][0]["mimeType"], "video/quicktime")
        credential, opener = Credential(), Opener(raw)
        target = self.directory / "prepared.mov"
        drive.VideoDriveClient(credential, opener=opener).download_video(metadata, target)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(credential.calls[0][2]["Accept"], "video/quicktime")

    def test_catalog_rejects_incomplete_source_and_skips_invalid_video_metadata(self):
        folder = self.configured()
        with self.assertRaisesRegex(drive.ReelDriveError, "catálogo completo"):
            drive.catalog(self.directory, CatalogClient({
                "complete": False, "folder_id": folder, "files": [],
            }))
        raw = mp4()
        result = drive.catalog(self.directory, CatalogClient({
            "complete": True, "folder_id": folder,
            "files": [item(raw, md5Checksum="")],
        }))
        self.assertEqual(result["total_videos"], 0)
        self.assertEqual(result["skipped_invalid_video"], 1)

    def test_download_streams_exact_mp4_atomically_and_read_only(self):
        raw = mp4(b"x" * (drive.CHUNK_BYTES + 50))
        metadata = item(raw)
        original = dict(metadata)
        credential, opener = Credential(), Opener(raw)
        client = drive.VideoDriveClient(credential, opener=opener)
        target = self.directory / "prepared.mp4"
        result = client.download_video(metadata, target)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result["bytes"], len(raw))
        self.assertEqual(metadata, original)
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertEqual((request.method, timeout), ("GET", drive.DOWNLOAD_TIMEOUT_SECONDS))
        self.assertEqual(request.get_header("Authorization"), "Bearer private-token")
        self.assertEqual(credential.calls[0][0], "GET")
        self.assertIn("alt=media", request.full_url)

    def test_download_rejects_wrong_type_size_checksum_and_non_mp4(self):
        raw = mp4()
        cases = [
            (item(raw, mimeType="application/vnd.google-apps.shortcut"), raw,
             "somente arquivos MP4 ou MOV"),
            (item(raw, size=str(len(raw) + 1)), raw, "tamanho confirmado"),
            (item(raw, md5Checksum="0" * 32), raw, "mudou desde a consulta"),
            (item(raw), b"not-an-mp4!", "tamanho confirmado"),
            (item(b"not-an-mp4!"), b"not-an-mp4!", "estrutura MP4"),
        ]
        for index, (metadata, response, message) in enumerate(cases):
            with self.subTest(index=index):
                target = self.directory / f"bad-{index}.mp4"
                client = drive.VideoDriveClient(Credential(), opener=Opener(response))
                with self.assertRaisesRegex(drive.ReelDriveError, message):
                    client.download_video(metadata, target)
                self.assertFalse(target.exists())
                self.assertEqual(list(self.directory.glob(".reel-drive-*")), [])

    def test_download_refuses_existing_destination_symlink_and_oversize_before_network(self):
        raw = mp4()
        opener = Opener(raw)
        client = drive.VideoDriveClient(Credential(), opener=opener)
        existing = self.directory / "existing.mp4"
        existing.write_bytes(b"keep")
        with self.assertRaisesRegex(drive.ReelDriveError, "novo arquivo"):
            client.download_video(item(raw), existing)
        link = self.directory / "link.mp4"
        link.symlink_to(existing)
        with self.assertRaisesRegex(drive.ReelDriveError, "novo arquivo"):
            client.download_video(item(raw), link)
        with self.assertRaisesRegex(drive.ReelDriveError, "limite seguro"):
            client.download_video(item(raw, size=str(drive.MAX_VIDEO_BYTES + 1)),
                                  self.directory / "large.mp4")
        self.assertEqual(opener.requests, [])

    def test_download_reports_network_timeout_without_leaving_partial_file(self):
        raw = mp4()

        class TimeoutOpener:
            def open(self, request, timeout=0):
                raise TimeoutError("private network detail")

        target = self.directory / "timeout.mp4"
        client = drive.VideoDriveClient(Credential(), opener=TimeoutOpener())
        with self.assertRaisesRegex(drive.ReelDriveError, "tempo de espera"):
            client.download_video(item(raw), target)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.directory.glob(".reel-drive-*")), [])

    def test_unexpected_download_failure_reports_safe_stage_and_exception_code(self):
        raw = mp4()

        class BrokenCredential(Credential):
            def before_request(self, transport, method, url, headers):
                raise RuntimeError("private credential detail")

        target = self.directory / "unexpected.mp4"
        client = drive.VideoDriveClient(BrokenCredential(), opener=Opener(raw))
        with self.assertRaisesRegex(
                drive.ReelDriveError,
                r"autenticação do download contínuo \(RuntimeError\)") as failure:
            client.download_video(item(raw), target)
        self.assertNotIn("private credential", str(failure.exception))

    def test_large_download_uses_verified_ranges_and_retries_only_failed_range(self):
        raw = mp4(b"ranged-video-data")
        metadata = item(raw)

        class RangedOpener:
            def __init__(self):
                self.requests = []
                self.failed = False

            def open(inner, request, timeout=0):
                inner.requests.append((request, timeout))
                value = request.get_header("Range")
                start, end = (int(part) for part in value.removeprefix("bytes=").split("-"))
                if start > 0 and not inner.failed:
                    inner.failed = True
                    raise TimeoutError("temporary private detail")
                return RangeResponse(raw[start:end + 1], f"bytes {start}-{end}/{len(raw)}")

        opener = RangedOpener()
        target = self.directory / "ranged.mp4"
        with patch("reels.drive.RANGE_DOWNLOAD_THRESHOLD", 1), \
                patch("reels.drive.RANGE_BYTES", 8):
            result = drive.VideoDriveClient(Credential(), opener=opener).download_video(
                metadata, target)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(result["bytes"], len(raw))
        ranges = [request.get_header("Range") for request, _ in opener.requests]
        self.assertEqual(ranges[:3], ["bytes=0-7", "bytes=8-15", "bytes=8-15"])
        self.assertTrue(all(timeout == drive.DOWNLOAD_TIMEOUT_SECONDS
                            for _, timeout in opener.requests))

    def test_large_download_retries_incomplete_http_range(self):
        raw = mp4(b"ranged-video-after-incomplete-http-read")
        metadata = item(raw)

        class IncompleteRangeOpener:
            def __init__(self):
                self.requests = []
                self.failed = False

            def open(inner, request, timeout=0):
                inner.requests.append(request)
                start, end = (int(part) for part in
                              request.get_header("Range").removeprefix("bytes=").split("-"))
                if not inner.failed:
                    inner.failed = True
                    raise http.client.IncompleteRead(b"partial", end - start + 1)
                return RangeResponse(raw[start:end + 1], f"bytes {start}-{end}/{len(raw)}")

        opener = IncompleteRangeOpener()
        target = self.directory / "incomplete-range.mp4"
        with patch("reels.drive.RANGE_DOWNLOAD_THRESHOLD", 1), \
                patch("reels.drive.RANGE_BYTES", 8):
            result = drive.VideoDriveClient(Credential(), opener=opener).download_video(
                metadata, target)

        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(result["bytes"], len(raw))
        self.assertGreater(len(opener.requests), len(raw) // 8)

    def test_large_download_falls_back_to_verified_continuous_stream(self):
        raw = mp4(b"large-video-with-range-fallback")
        metadata = item(raw)

        class RangeRejectedOpener:
            def __init__(self):
                self.requests = []

            def open(inner, request, timeout=0):
                inner.requests.append(request)
                return Response(raw)

        opener = RangeRejectedOpener()
        target = self.directory / "range-fallback.mp4"
        with patch("reels.drive.RANGE_DOWNLOAD_THRESHOLD", 1), \
                patch("reels.drive.RANGE_BYTES", 8):
            result = drive.VideoDriveClient(Credential(), opener=opener).download_video(
                metadata, target)

        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(result["bytes"], len(raw))
        self.assertIsNotNone(opener.requests[0].get_header("Range"))
        self.assertIsNone(opener.requests[-1].get_header("Range"))

    def test_busy_fsync_does_not_reject_integrity_checked_download(self):
        raw = mp4(b"pythonanywhere-busy-fsync")
        target = self.directory / "busy-fsync.mp4"
        with patch("reels.drive.os.fsync", side_effect=OSError(errno.EBUSY, "busy")):
            result = drive.VideoDriveClient(
                Credential(), opener=Opener(raw)).download_video(item(raw), target)

        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(result["md5"], hashlib.md5(raw, usedforsecurity=False).hexdigest())

    def test_operator_cli_configures_and_checks_drive_without_enabling_publishing(self):
        output = io.StringIO()
        with patch("reels.drive.configure", return_value="reels@example.test") as configure, \
                redirect_stdout(output):
            drive.main([
                "configure", "--directory", str(self.directory),
                "--folder", "folderIdentifier123",
            ])
        configure.assert_called_once_with(self.directory, "folderIdentifier123")
        self.assertEqual(json.loads(output.getvalue())["publishing_enabled"], False)

        output = io.StringIO()
        result = {
            "complete": True, "folder_name": "Ready Reels", "total_videos": 2,
            "skipped_non_video": 1, "skipped_invalid_video": 0,
        }
        with patch("reels.drive.catalog", return_value=result) as catalog, redirect_stdout(output):
            drive.main(["status", "--directory", str(self.directory)])
        catalog.assert_called_once_with(self.directory)
        self.assertEqual(json.loads(output.getvalue())["total_videos"], 2)


if __name__ == "__main__":
    unittest.main()
