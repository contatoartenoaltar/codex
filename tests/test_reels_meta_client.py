import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

import meta
from reels.meta_client import (ACCOUNT, MAX_RESPONSE, SCOPES, MetaClient,
    MetaRejectedError, NoRedirect, PreparationRetryError, PublishUncertainError,
    credentials)


SETTINGS = {"version": "v24.0", "app_secret": "synthetic-app-secret",
            "app_id": "123", "config_id": "456"}
TOKEN = "synthetic-user-token"
ORIGIN = "https://artenoaltar.pythonanywhere.com"
VIDEO = ORIGIN + "/reels-media/" + "a" * 64 + ".mp4"


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value if isinstance(value, bytes) else json.dumps(value).encode())


def verification(**changes):
    permissions = {"data": [{"permission": value, "status": "granted"} for value in SCOPES]}
    return [permissions, {"id": "123456", "username": ACCOUNT} | changes]


class ReelsMetaClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def client(self, responses):
        opener = Opener(responses)
        return MetaClient(SETTINGS, TOKEN, "123456", ORIGIN, opener=opener), opener

    def test_verifies_exact_account_and_required_permissions(self):
        client, opener = self.client(verification())
        self.assertEqual(client.verify_account("123456"), {
            "id": "123456", "username": ACCOUNT, "reels_allowed": True})
        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(all(item[0].get_method() == "GET" for item in opener.requests))
        self.assertTrue(all(item[0].get_header("Authorization") == "Bearer " + TOKEN
                            for item in opener.requests))
        self.assertNotIn(TOKEN, " ".join(item[0].full_url for item in opener.requests))

    def test_wrong_account_username_or_permissions_are_rejected(self):
        cases = [[{"data": []}], verification(username="other.account")]
        for responses in cases:
            client, _ = self.client(responses)
            with self.subTest(responses=responses), self.assertRaises(ValueError):
                client.verify_account("123456")
        client, opener = self.client([])
        with self.assertRaises(ValueError):
            client.verify_account("999")
        self.assertEqual(opener.requests, [])

    def test_creates_reels_container_with_public_video_caption_and_feed_flag(self):
        client, opener = self.client([{"id": "800"}])
        self.assertEqual(client.create_container(VIDEO, "  Conheça nossos envelopes  "), {"id": "800"})
        request, timeout = opener.requests[0]
        self.assertEqual(timeout, 10)
        self.assertTrue(request.full_url.endswith("/v24.0/123456/media"))
        fields = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(fields["media_type"], ["REELS"])
        self.assertEqual(fields["video_url"], [VIDEO])
        self.assertEqual(fields["caption"], ["Conheça nossos envelopes"])
        self.assertEqual(fields["share_to_feed"], ["true"])
        proof = hmac.new(SETTINGS["app_secret"].encode(), TOKEN.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(fields["appsecret_proof"], [proof])

    def test_accepts_temporary_mov_url_from_same_origin(self):
        mov = ORIGIN + "/reels-media/" + "b" * 64 + ".mov"
        client, opener = self.client([{"id": "801"}])
        self.assertEqual(client.create_container(mov, "Reel do Edits"), {"id": "801"})
        fields = urllib.parse.parse_qs(opener.requests[0][0].data.decode())
        self.assertEqual(fields["video_url"], [mov])

    def test_rejects_unapproved_video_urls_caption_and_feed_configuration_before_network(self):
        client, opener = self.client([])
        bad_urls = [
            "http://artenoaltar.pythonanywhere.com/reels-media/" + "a" * 64 + ".mp4",
            "https://evil.example/reels-media/" + "a" * 64 + ".mp4",
            ORIGIN + "/media/" + "a" * 64 + ".mp4",
            VIDEO + "?token=secret",
            ORIGIN + "/reels-media/not-a-token.mp4",
        ]
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.create_container(url, "Legenda")
        for caption in ("", "x" * 2201):
            with self.assertRaises(ValueError):
                client.create_container(VIDEO, caption)
        with self.assertRaises(ValueError):
            client.create_container(VIDEO, "Legenda", share_to_feed=False)
        self.assertEqual(opener.requests, [])

    def test_status_and_final_publish_are_separate(self):
        client, opener = self.client([{"status_code": "FINISHED"}, {"id": "900"}])
        self.assertEqual(client.container_status("800"), "FINISHED")
        self.assertEqual(client.publish("800"), {"id": "900"})
        fields = urllib.parse.parse_qs(opener.requests[-1][0].data.decode())
        self.assertEqual(fields["creation_id"], ["800"])
        self.assertTrue(opener.requests[-1][0].full_url.endswith("/123456/media_publish"))

    def test_final_publish_network_loss_is_distinct_and_never_leaks_credentials(self):
        for failure in (TimeoutError(TOKEN), urllib.error.URLError(TOKEN), b"{bad json",
                        b"x" * (MAX_RESPONSE + 1), {"unexpected": "response"}):
            client, _ = self.client([failure])
            with self.subTest(failure=type(failure).__name__), \
                    self.assertRaises(PublishUncertainError) as caught:
                client.publish("800")
            self.assertNotIn(TOKEN, str(caught.exception))
        client, _ = self.client([urllib.error.HTTPError(
            "https://graph.facebook.com", 400, TOKEN, {}, io.BytesIO(TOKEN.encode()))])
        with self.assertRaises(MetaRejectedError) as caught:
            client.publish("800")
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_preparation_failure_is_retryable_and_strict_paths_are_enforced(self):
        client, opener = self.client([TimeoutError(TOKEN)])
        with self.assertRaises(PreparationRetryError):
            client.create_container(VIDEO, "Legenda")
        for operation in (lambda: client.container_status("../feed"),
                          lambda: client.publish("https://evil.example")):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(len(opener.requests), 1)
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example")

    def test_existing_credentials_are_read_only_and_expired_or_symlinked_are_refused(self):
        meta.write_private(self.directory / "meta-config.json", SETTINGS)
        meta.write_private(self.directory / "meta-connection.json", {
            "app_id": "123", "access_token": TOKEN, "expires_at": 4102444800})
        before = {path.name: path.read_bytes() for path in self.directory.glob("*.json")}
        with patch.dict(os.environ, {
                "ARTENOALTAR_META_APP_ID": "123", "ARTENOALTAR_META_CONFIG_ID": "456",
                "ARTENOALTAR_META_APP_SECRET": SETTINGS["app_secret"]}):
            self.assertEqual(credentials(self.directory)[1], TOKEN)
            self.assertEqual({path.name: path.read_bytes() for path in self.directory.glob("*.json")}, before)
            meta.write_private(self.directory / "meta-connection.json", {
                "app_id": "123", "access_token": TOKEN, "expires_at": 1})
            with self.assertRaises(ValueError):
                credentials(self.directory)
        (self.directory / "meta-connection.json").unlink()
        (self.directory / "meta-connection.json").symlink_to(self.directory / "meta-config.json")
        with self.assertRaises(ValueError):
            credentials(self.directory)


if __name__ == "__main__":
    unittest.main()
