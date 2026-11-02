import hashlib
import hmac
import io
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

from PIL import Image
import meta
from stories.meta_client import MetaClient, NoRedirect, SCOPES, credentials, MAX_RESPONSE


SETTINGS = {'version': 'v24.0', 'app_secret': 'synthetic-app-secret', 'app_id': '123', 'config_id': '456'}
TOKEN = 'synthetic-user-token'
PAGE_TOKEN = 'synthetic-page-token'


def verification(**changes):
    account = {'id': '123456', 'username': 'arte.no.altar'} | changes
    return [{'data': [{'permission': p, 'status': 'granted'} for p in SCOPES]}, account,
            {'data': [{'id': '222', 'instagram_business_account': {'id': '123456'}, 'access_token': PAGE_TOKEN}]}]


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


class StoryMetaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.image = self.directory/'story.jpg'
        Image.new('RGB', (1080, 1920), 'white').save(self.image)

    def client(self, responses):
        opener = Opener(responses)
        return MetaClient(SETTINGS, TOKEN, '123456', opener=opener), opener

    def test_verification_requires_exact_linked_business_account_and_permissions(self):
        client, opener = self.client(verification())
        result = client.verify_account('123456')
        self.assertTrue(result['stories_allowed'])
        self.assertEqual(result['account_type'], 'BUSINESS')
        self.assertEqual(len(opener.requests), 3)
        for request, timeout in opener.requests:
            self.assertEqual(request.get_method(), 'GET')
            self.assertTrue(request.full_url.startswith('https://graph.facebook.com/v24.0/'))
            self.assertNotIn(TOKEN, request.full_url)
            self.assertEqual(request.get_header('Authorization'), 'Bearer '+TOKEN)
            self.assertEqual(timeout, 5)
        account_query = urllib.parse.parse_qs(urllib.parse.urlsplit(opener.requests[1][0].full_url).query)
        self.assertEqual(account_query['fields'], ['id,username'])
        self.assertNotIn('account_type', opener.requests[1][0].full_url)
        page_query = urllib.parse.parse_qs(urllib.parse.urlsplit(opener.requests[2][0].full_url).query)
        self.assertEqual(page_query['fields'],
                         ['id,instagram_business_account{id},connected_instagram_account{id},access_token'])

    def test_current_connected_instagram_account_field_is_accepted(self):
        responses = verification()
        page = responses[2]['data'][0]
        page['connected_instagram_account'] = page.pop('instagram_business_account')
        client, _ = self.client(responses)
        self.assertEqual(client.verify_account('123456')['username'], 'arte.no.altar')

    def test_other_username_missing_permission_and_invalid_page_links_are_rejected(self):
        linked = {'id': '222', 'instagram_business_account': {'id': '123456'}, 'access_token': PAGE_TOKEN}
        cases = [verification(username='another.account'), [{'data': []}],
                 verification()[:2] + [{'data': [{'id': '222', 'instagram_business_account': {'id': '999'}}]}],
                 verification()[:2] + [{'data': [linked, linked | {'id': '333'}]}],
                 verification()[:2] + [{'data': [linked | {
                     'connected_instagram_account': {'id': '999'}}]}],
                 verification()[:2] + [{'data': [linked | {'access_token': ''}]}]]
        for responses in cases:
            with self.subTest(responses=responses):
                client, opener = self.client(responses)
                with self.assertRaises(ValueError):
                    client.verify_account('123456')
                self.assertTrue(all(r.get_method() == 'GET' for r, _ in opener.requests))

    def test_staging_uploads_only_unpublished_photo_to_exact_linked_page(self):
        client, opener = self.client(verification()+[{'id': '700'}])
        client.verify_account('123456')
        self.assertEqual(client.stage_image(self.image), {'id': '700'})
        request, _ = opener.requests[-1]
        self.assertTrue(request.full_url.endswith('/222/photos'))
        self.assertEqual(request.get_header('Authorization'), 'Bearer '+PAGE_TOKEN)
        self.assertIn(b'name="published"\r\n\r\nfalse', request.data)
        self.assertNotIn(b'\r\n\r\ntrue', request.data)
        self.assertIn(self.image.read_bytes(), request.data)
        proof = hmac.new(SETTINGS['app_secret'].encode(), PAGE_TOKEN.encode(), hashlib.sha256).hexdigest()
        self.assertIn(proof.encode(), request.data)
        self.assertNotIn(TOKEN.encode(), request.data)
        self.assertFalse(any('/media_publish' in r.full_url for r, _ in opener.requests))

    def test_story_container_uses_portrait_cdn_image_and_never_caption_or_feed_format(self):
        photo = {'images': [{'source': 'https://s.example.fbcdn.net/story.jpg?sig=opaque', 'width': 1080, 'height': 1920},
                            {'source': 'https://s.example.fbcdn.net/thumb.jpg', 'width': 320, 'height': 320}]}
        client, opener = self.client(verification()+[photo, {'id': '800'}])
        client.verify_account('123456')
        self.assertEqual(client.create_container(self.image, media_type='STORIES', staged_photo='700'), {'id': '800'})
        request, _ = opener.requests[-1]
        fields = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(fields['media_type'], ['STORIES'])
        self.assertEqual(fields['image_url'], ['https://s.example.fbcdn.net/story.jpg?sig=opaque'])
        self.assertNotIn('caption', fields)
        self.assertTrue(request.full_url.endswith('/123456/media'))

    def test_arbitrary_image_destinations_and_square_thumbnails_are_rejected(self):
        for url, width, height in [('https://evil.example/story.jpg', 1080, 1920),
                                   ('https://cdn.fbcdn.net.evil.example/a.jpg', 1080, 1920),
                                   ('http://s.example.fbcdn.net/a.jpg', 1080, 1920),
                                   ('https://s.example.fbcdn.net/a.jpg', 320, 320)]:
            client, opener = self.client(verification()+[{'images': [{'source': url, 'width': width, 'height': height}]}])
            client.verify_account('123456')
            with self.assertRaises(ValueError):
                client.create_container(self.image, media_type='STORIES', staged_photo='700')
            self.assertTrue(all(r.get_method() == 'GET' for r, _ in opener.requests))

    def test_status_and_publish_are_separate_calls_with_persistable_ids(self):
        client, opener = self.client([{'status_code': 'FINISHED'}, {'id': '900'}])
        self.assertEqual(client.container_status('800'), 'FINISHED')
        self.assertEqual(client.publish('800'), {'id': '900'})
        request, _ = opener.requests[-1]
        self.assertEqual(urllib.parse.parse_qs(request.data.decode())['creation_id'], ['800'])
        self.assertTrue(request.full_url.endswith('/123456/media_publish'))

    def test_invalid_ids_other_format_and_invalid_credentials_never_make_requests(self):
        client, opener = self.client([])
        for operation in (lambda: client.publish('../feed'), lambda: client.container_status('https://evil.example'),
                          lambda: client.verify_account('999'),
                          lambda: client.create_container(self.image, media_type='IMAGE', staged_photo='700'),
                          lambda: client.stage_image(self.image)):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(opener.requests, [])
        with self.assertRaises(ValueError):
            MetaClient(SETTINGS | {'version': 'https://evil.example'}, TOKEN, '123456')

    def test_redirects_large_responses_errors_and_lost_results_do_not_expose_secrets(self):
        errors = [TimeoutError(TOKEN), urllib.error.URLError(PAGE_TOKEN),
                  urllib.error.HTTPError('https://graph.facebook.com', 400, TOKEN, {}, io.BytesIO(TOKEN.encode())),
                  {'error': {'message': TOKEN}}, b'{bad json', b'x'*(MAX_RESPONSE+1), {'id': ''}]
        for error in errors:
            client, _ = self.client([error])
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(ValueError) as caught:
                    client.publish('800')
                self.assertNotIn(TOKEN, str(caught.exception))
                self.assertNotIn(PAGE_TOKEN, str(caught.exception))
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')

    def test_existing_credentials_are_read_only_and_expired_or_symlinked_are_refused(self):
        meta.write_private(self.directory/'meta-config.json', SETTINGS)
        meta.write_private(self.directory/'meta-connection.json', {'app_id': '123', 'access_token': TOKEN, 'expires_at': 4102444800})
        before = {p.name: p.read_bytes() for p in self.directory.glob('*.json')}
        with patch.dict(os.environ, {'ARTENOALTAR_META_APP_ID': '123', 'ARTENOALTAR_META_CONFIG_ID': '456',
                                    'ARTENOALTAR_META_APP_SECRET': SETTINGS['app_secret']}):
            self.assertEqual(credentials(self.directory)[1], TOKEN)
            self.assertEqual({p.name: p.read_bytes() for p in self.directory.glob('*.json')}, before)
            for expiry in (1, float('nan'), float('inf'), True):
                meta.write_private(self.directory/'meta-connection.json', {'app_id': '123', 'access_token': TOKEN, 'expires_at': expiry})
                with self.assertRaises(ValueError):
                    credentials(self.directory)
        (self.directory/'meta-connection.json').unlink()
        (self.directory/'meta-connection.json').symlink_to(self.directory/'meta-config.json')
        with self.assertRaises(ValueError):
            credentials(self.directory)

    def test_real_queue_adapter_pipeline_uses_mock_http_and_persists_each_receipt(self):
        from stories.queue import Store, ZONE, configure_live, prepare_batch, queue_batch, enable_live, tick
        store = Store(self.directory/'isolated-live-fixture')
        store.initialize()
        now = datetime(2026, 11, 2, 18, tzinfo=ZONE)
        configure_live(store, '123456', confirmed=True)
        batch = prepare_batch(store, now=now)['batch_id']
        queue_batch(store, batch, confirmed=True, now=now)
        enable_live(store, confirmed=True, now=now)
        responses = (verification()+[{'id': '700'}]+verification()+
                     [{'images': [{'source': 'https://s.example.fbcdn.net/story.jpg', 'width': 1080, 'height': 1920}]},
                      {'id': '800'}]+verification()+[{'status_code': 'FINISHED'}, {'id': '900'}])
        client, opener = self.client(responses)
        due = datetime.fromtimestamp(store.agenda()[0]['due_at'], ZONE)
        self.assertEqual(tick(store, client, now=due)['status'], 'staged')
        self.assertEqual(tick(store, client, now=due+timedelta(minutes=1))['status'], 'processing')
        self.assertEqual(tick(store, client, now=due+timedelta(minutes=2))['status'], 'published')
        row = store.agenda()[0]
        self.assertEqual((row['staged_photo'], row['container'], row['remote_id']), ('700', '800', '900'))
        posts = [r for r, _ in opener.requests if r.get_method() == 'POST']
        self.assertEqual([urllib.parse.urlsplit(r.full_url).path for r in posts],
                         ['/v24.0/222/photos', '/v24.0/123456/media', '/v24.0/123456/media_publish'])
        self.assertNotIn(TOKEN, str(store.agenda()))
        self.assertNotIn(PAGE_TOKEN, str(store.agenda()))
