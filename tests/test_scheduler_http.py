import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import app
import meta
import scheduler_http as trigger
import scheduling
import wsgi


class SchedulerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'test.db'
        app.initialize()
        self.key = 'scheduler-exclusive-test-key-32-characters'
        (app.DB.parent / trigger.HASH_FILE).write_text(hashlib.sha256(self.key.encode()).hexdigest())
        meta.write_private(app.DB.parent / 'meta-config.json',
                           {'app_id': '123', 'config_id': '456', 'app_secret': 'test-secret'})
        self.env = patch.dict(os.environ, {'ARTENOALTAR_ORIGIN': 'https://gestao.example'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        app.DB = self.old_db
        self.temp.cleanup()

    def http(self, key=None, method='POST', body=b'', **extra):
        env = {'PATH_INFO': trigger.PATH, 'REQUEST_METHOD': method,
               'HTTP_HOST': 'gestao.example', 'CONTENT_LENGTH': str(len(body)),
               'HTTP_AUTHORIZATION': 'Bearer ' + (self.key if key is None else key),
               'wsgi.input': io.BytesIO(body)}
        env.update(extra)
        result = {}
        def start(status, headers):
            result['status'] = int(status.split()[0])
            result['headers'] = dict(headers)
        result['body'] = json.loads(b''.join(wsgi.application(env, start)))
        return result

    def post(self, state, due):
        with app.connect() as c:
            p = c.execute("INSERT INTO posts(product,channel,caption,source,account_id,publish_status) VALUES('Envelope','Facebook','Legenda aprovada','Teste','999',?)", (state,))
            if state == 'scheduled':
                c.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(?,0,?,'queued')", (p.lastrowid, due))
            return p.lastrowid

    def test_authentication_and_request_rejections_never_run_queue(self):
        with patch('scheduling.tick') as tick:
            for extras, expected in [({'key': 'wrong'}, 401),
                                     ({'HTTP_AUTHORIZATION': ''}, 401),
                                     ({'HTTP_ORIGIN': 'https://gestao.example'}, 403),
                                     ({'QUERY_STRING': 'key=do-not-use'}, 400),
                                     ({'body': b'{"id":1,"confirmed":true}'}, 400),
                                     ({'HTTP_TRANSFER_ENCODING': 'chunked'}, 400),
                                     ({'method': 'GET'}, 405),
                                     ({'HTTP_HOST': 'evil.example'}, 403)]:
                self.assertEqual(self.http(**extras)['status'], expected, extras)
            (app.DB.parent / trigger.HASH_FILE).unlink()
            self.assertEqual(self.http()['status'], 503)
            tick.assert_not_called()
        with app.connect() as c:
            self.assertIsNone(c.execute('SELECT * FROM scheduler_runtime').fetchone())

    def test_no_early_or_unapproved_publications_and_receipt_has_no_content(self):
        now = int(time.time())
        self.post('draft', now - 60)
        self.post('scheduled', now + 120)
        with patch('publishing.publish') as publish:
            result = self.http()
            self.assertEqual(result['status'], 200)
            self.assertEqual(result['body'], {'status': 'idle'})
            self.assertEqual(result['headers']['Cache-Control'], 'no-store')
            publish.assert_not_called()
        with app.connect() as c:
            self.assertTrue(scheduling.runtime(c)['active'])
        self.assertEqual(self.http()['body'], {'status': 'throttled'})

    def test_due_post_runs_once_even_if_trigger_is_repeated(self):
        now = int(time.time())
        self.post('scheduled', now - 1)
        with patch('publishing.publish', return_value={'status': 'published'}) as publish:
            self.assertEqual(self.http()['body'], {'status': 'done'})
            self.assertEqual(self.http()['body'], {'status': 'throttled'})
            with patch('time.time', return_value=now + 61):
                self.assertEqual(self.http()['body'], {'status': 'idle'})
            self.assertEqual(publish.call_count, 1)
        # Esta chave não concede sessão de proprietário nem acesso financeiro.
        self.assertEqual(self.http(PATH_INFO='/api/state', method='GET')['status'], 401)

    def test_concurrent_trigger_cannot_start_another_tick(self):
        def during_tick(*args, **kwargs):
            self.assertEqual(self.http()['body'], {'status': 'busy'})
            return {'status': 'idle'}
        with patch('scheduling.tick', side_effect=during_tick) as tick:
            self.assertEqual(self.http()['body'], {'status': 'idle'})
            self.assertEqual(tick.call_count, 1)

    def test_lost_runner_expires_and_failed_http_releases_lease(self):
        now = int(time.time())
        with patch('scheduling.tick', side_effect=ValueError('private detail')):
            response = self.http()
            self.assertEqual(response['status'], 503)
            self.assertNotIn('private detail', str(response))
        with patch('time.time', return_value=now + 61):
            self.assertEqual(self.http()['body'], {'status': 'idle'})
        with app.connect() as c, patch('time.time', return_value=now + 212):
            self.assertFalse(scheduling.runtime(c)['active'])

    def test_expired_lease_does_not_retry_uncertain_publication(self):
        now = int(time.time())
        post = self.post('scheduled', now - 700)
        with app.connect() as c:
            c.execute("UPDATE post_schedule SET state='running',claimed_at=? WHERE post_id=?", (now - 601, post))
            c.execute("INSERT INTO scheduler_http_runtime VALUES(1,?,'lost-process',?)", (now - 601, now - 1))
        with patch('publishing.publish') as publish:
            self.assertEqual(self.http()['body'], {'status': 'idle'})
            publish.assert_not_called()
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT publish_status FROM posts WHERE id=?', (post,)).fetchone()[0], 'review')

    def test_configure_private_key_and_rotation(self):
        (app.DB.parent / trigger.HASH_FILE).unlink()
        trigger.configure(app.DB.parent)
        key_path = app.DB.parent / trigger.KEY_FILE
        hash_path = app.DB.parent / trigger.HASH_FILE
        for path in (key_path, hash_path):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        key = key_path.read_text().strip()
        self.assertEqual(self.http(key=key)['status'], 200)
        with self.assertRaises(ValueError):
            trigger.configure(app.DB.parent)
        trigger.configure(app.DB.parent, rotate=True)
        self.assertNotEqual(key_path.read_text().strip(), key)
        self.assertEqual(self.http(key=key)['status'], 401)
