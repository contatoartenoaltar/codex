import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

import drive_source as drive

ROOT = 'root_folder_0001'
CHILD = 'child_folder_0002'


class Response(io.BytesIO):
    def __init__(self, value, code=200):
        super().__init__(json.dumps(value).encode())
        self.code = code
        self.headers = {'Content-Type': 'application/json'}

    def getcode(self):
        return self.code


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return Response(result)


class Credential:
    def before_request(self, transport, method, url, headers):
        headers['Authorization'] = 'Bearer synthetic-test-token'


class DriveSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def account(self, **changes):
        info = {'type': 'service_account', 'client_email': 'source-reader@sample.iam.gserviceaccount.com',
                'token_uri': drive.TOKEN_URI, 'private_key': 'synthetic-private-value',
                'private_key_id': 'synthetic-key-id'} | changes
        drive.write_private(self.directory / drive.CREDENTIALS_FILE, info)
        return info

    def root(self):
        return {'id': ROOT, 'name': 'Modelos à venda', 'mimeType': drive.FOLDER_MIME}

    def entries(self):
        return [self.root(), {'nextPageToken': 'page2', 'files': [
            {'id': CHILD, 'name': 'Envelopes', 'mimeType': drive.FOLDER_MIME},
            {'id': 'image_file_0001', 'name': 'Modelo 1.jpg', 'mimeType': 'image/jpeg', 'size': '1200'},
            {'id': 'shortcut_0001', 'name': 'Outra pasta', 'mimeType': drive.SHORTCUT_MIME}]},
            {'files': [{'id': 'source_file_0002', 'name': 'Original.psd', 'mimeType': 'image/vnd.adobe.photoshop'}]},
            {'files': [{'id': 'image_file_0003', 'name': 'Modelo 2.png', 'mimeType': 'image/png'},
                       {'id': 'text_file_00004', 'name': 'Observações.txt', 'mimeType': 'text/plain'}]}]

    def test_folder_link_validation_does_not_accept_arbitrary_urls(self):
        self.assertEqual(drive.folder_id('https://drive.google.com/drive/u/1/folders/' + ROOT), ROOT)
        self.assertEqual(drive.folder_id(ROOT), ROOT)
        for value in ['http://drive.google.com/drive/folders/' + ROOT,
                      'https://evil.example/drive/folders/' + ROOT,
                      'https://drive.google.com@evil.example/drive/folders/' + ROOT,
                      'https://drive.google.com/file/d/' + ROOT, '../credentials', "x' in parents"]:
            with self.subTest(value=value), self.assertRaises(drive.DriveError):
                drive.folder_id(value)

    def test_recursive_paginated_counts_are_read_only_and_folder_scoped(self):
        opener = Opener(self.entries())
        result = drive.DriveClient(Credential(), opener).catalog(ROOT)
        self.assertEqual((result['total_files'], result['total_images']), (4, 3))
        self.assertEqual(result['formats'], {'image/jpeg': 1, 'image/png': 1,
                                          'image/vnd.adobe.photoshop': 1, 'text/plain': 1})
        self.assertEqual([s['path'] for s in result['subfolders']], [['Envelopes']])
        self.assertEqual(result['skipped_shortcuts'], 1)
        self.assertTrue(result['complete'])
        for request in opener.requests:
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(urllib.parse.urlsplit(request.full_url).hostname, 'www.googleapis.com')
            self.assertIsNone(request.data)
        queries = [urllib.parse.parse_qs(urllib.parse.urlsplit(r.full_url).query) for r in opener.requests[1:]]
        self.assertEqual([q['q'][0] for q in queries], [f"'{ROOT}' in parents and trashed = false"] * 2 + [f"'{CHILD}' in parents and trashed = false"])
        self.assertEqual(queries[1]['pageToken'], ['page2'])
        self.assertNotIn('synthetic-test-token', json.dumps(result))

    def test_configuration_is_private_and_does_not_claim_verified_access(self):
        self.account()
        email = drive.configure(self.directory, ROOT)
        self.assertEqual(email, 'source-reader@sample.iam.gserviceaccount.com')
        config = drive.read_json(self.directory / drive.CONFIG_FILE)
        self.assertFalse(config['access_verified'])
        self.assertNotIn('private_key', config)
        for name in (drive.CONFIG_FILE, drive.CREDENTIALS_FILE):
            self.assertEqual((self.directory / name).stat().st_mode & 0o777, 0o600)

    def test_unsafe_credential_endpoints_and_credential_symlinks_are_rejected(self):
        for changes in [{'type': 'api_key'}, {'token_uri': 'https://evil.example/token'},
                        {'universe_domain': 'evil.example'}, {'client_email': 'not-a-service-account'}]:
            self.account(**changes)
            with self.assertRaises(drive.DriveError):
                drive.account_info(self.directory)
        (self.directory / drive.CREDENTIALS_FILE).unlink()
        (self.directory / 'elsewhere.json').write_text('{}')
        (self.directory / drive.CREDENTIALS_FILE).symlink_to(self.directory / 'elsewhere.json')
        with self.assertRaises(drive.DriveError):
            drive.account_info(self.directory)

    def test_inspection_saves_only_private_metadata_after_success(self):
        self.account()
        drive.configure(self.directory, ROOT)
        result = drive.inspect(self.directory, drive.DriveClient(Credential(), Opener(self.entries())))
        path = self.directory / drive.CATALOG_FILE
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        stored = path.read_text()
        self.assertNotIn('synthetic-private-value', stored)
        self.assertNotIn('synthetic-test-token', stored)
        self.assertEqual(json.loads(stored)['total_images'], result['total_images'])
        self.assertTrue(drive.read_json(self.directory / drive.CONFIG_FILE)['access_verified'])

    def test_failed_or_incomplete_queries_preserve_previous_catalog(self):
        self.account()
        drive.configure(self.directory, ROOT)
        sentinel = {'complete': True, 'previous': 'keep-this-catalog'}
        drive.write_private(self.directory / drive.CATALOG_FILE, sentinel)
        for response in [{'incompleteSearch': True, 'files': []}, {'files': 'malformed'}]:
            with self.assertRaises(drive.DriveError):
                drive.inspect(self.directory, drive.DriveClient(Credential(), Opener([self.root(), response])))
            self.assertEqual(drive.read_json(self.directory / drive.CATALOG_FILE), sentinel)

    def test_oversized_catalog_and_repeated_pagination_fail_without_partial_result(self):
        with patch('drive_source.MAX_FILES', 1), self.assertRaises(drive.DriveError):
            drive.DriveClient(Credential(), Opener(self.entries())).catalog(ROOT)
        pages = [self.root(), {'nextPageToken': 'same', 'files': []},
                 {'nextPageToken': 'same', 'files': []}]
        with self.assertRaises(drive.DriveError):
            drive.DriveClient(Credential(), Opener(pages)).catalog(ROOT)

    def test_permission_errors_are_sanitized(self):
        error = urllib.error.HTTPError(drive.API, 403, 'synthetic-private-value', {}, io.BytesIO(b'private provider detail'))
        with self.assertRaises(drive.DriveError) as caught:
            drive.DriveClient(Credential(), Opener([error])).catalog(ROOT)
        self.assertNotIn('synthetic-private-value', str(caught.exception))
        self.assertNotIn('private provider detail', str(caught.exception))

    def test_redirects_and_arbitrary_auth_destinations_are_rejected(self):
        with self.assertRaises(drive.DriveError):
            drive.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')
        with self.assertRaises(drive.DriveError):
            drive.TokenTransport(Opener([]))('https://evil.example', method='POST', body=b'assertion=secret')

    def test_official_google_auth_signs_only_readonly_scope_and_uses_bounded_transport(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from google.auth import jwt
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        self.account(private_key=pem)
        credential = drive.credentials(self.directory)
        auth_opener = Opener([{'access_token': 'synthetic-oauth-token', 'expires_in': 3600,
                               'token_type': 'Bearer'}])
        files_opener = Opener([self.root()])
        client = drive.DriveClient(credential, files_opener)
        client.transport = drive.TokenTransport(auth_opener)
        result = client.get(ROOT, {'fields': 'id,name,mimeType'})
        self.assertEqual(result['id'], ROOT)
        auth_request = auth_opener.requests[0]
        self.assertEqual(auth_request.full_url, drive.TOKEN_URI)
        assertion = urllib.parse.parse_qs(auth_request.data.decode())['assertion'][0]
        claims = jwt.decode(assertion, verify=False)
        self.assertEqual(claims['scope'], drive.SCOPE)
        self.assertEqual(claims['aud'], drive.TOKEN_URI)
        self.assertNotIn('sub', claims)
        self.assertEqual(files_opener.requests[0].get_header('Authorization'), 'Bearer synthetic-oauth-token')
