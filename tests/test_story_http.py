from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import app
import wsgi as existing_wsgi
from stories import http
from stories import wsgi as story_wsgi
from stories.queue import Store, ZONE, configure_live, prepare_batch, queue_batch, enable_live


class Client:
    simulation = False
    requires_staging = True
    account_id = '123456'


class StoryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'stories'
        http.configure(self.directory, 'https://gestao.example')
        self.key = (self.directory/http.KEY_FILE).read_text()
        self.store = Store(self.directory)
        self.now = datetime(2026, 11, 2, 18, tzinfo=ZONE)
        self.factory = Mock(return_value=Client())
        self.env = {'PATH_INFO': http.PATH, 'REQUEST_METHOD': 'POST', 'HTTP_HOST': 'gestao.example',
                    'HTTP_AUTHORIZATION': 'Bearer '+self.key, 'CONTENT_LENGTH': '0', 'QUERY_STRING': ''}

    def ready(self):
        configure_live(self.store, '123456', confirmed=True)
        batch = prepare_batch(self.store, now=self.now)['batch_id']
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        enable_live(self.store, confirmed=True, now=self.now)

    def call(self, changes=None, *, now=None):
        return http.handle(self.env | (changes or {}), self.directory, self.factory, now=now or self.now)

    def test_invalid_auth_query_browser_origin_method_host_and_body_do_not_construct_client(self):
        for changes, status in [({'HTTP_AUTHORIZATION': ''}, 401),
                                ({'HTTP_AUTHORIZATION': 'Bearer '+'feed-key-'+'x'*40}, 401),
                                ({'QUERY_STRING': 'key=not-accepted'}, 400), ({'HTTP_ORIGIN': ''}, 403),
                                ({'REQUEST_METHOD': 'GET'}, 405), ({'HTTP_HOST': 'evil.example'}, 403),
                                ({'CONTENT_LENGTH': '1'}, 400), ({'HTTP_TRANSFER_ENCODING': 'chunked'}, 400)]:
            with self.subTest(changes=changes):
                self.assertEqual(self.call(changes)[0], status)
        self.factory.assert_not_called()

    def test_disabled_policy_and_simulation_never_read_real_credentials(self):
        self.assertEqual(self.call(), (200, {'status': 'disabled'}))
        from stories.queue import enable_simulation
        enable_simulation(self.store, '123456', confirmed=True)
        self.assertEqual(self.call(), (200, {'status': 'unconfigured'}))
        self.factory.assert_not_called()

    def test_configure_does_not_replace_any_existing_key(self):
        before = {p.name: p.read_bytes() for p in self.directory.glob('stories-*')}
        with self.assertRaises(FileExistsError):
            http.configure(self.directory, 'https://gestao.example')
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.glob('stories-*')}, before)
        self.assertEqual((self.directory/http.KEY_FILE).stat().st_mode & 0o777, 0o600)
        (self.directory/http.CONFIG_FILE).chmod(0o644)
        self.assertEqual(self.call()[0], 503)

    def test_live_tick_is_throttled_and_lease_is_released(self):
        self.ready()
        self.assertEqual(self.call(), (200, {'status': 'idle'}))
        self.assertEqual(self.call(now=self.now+timedelta(seconds=10)), (200, {'status': 'throttled'}))
        self.assertEqual(self.call(now=self.now+timedelta(seconds=31)), (200, {'status': 'idle'}))
        self.assertEqual(self.factory.call_count, 2)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT lease_until FROM http_runtime').fetchone()[0], 0)

    def test_parallel_http_calls_use_one_lease(self):
        self.ready()
        entered, release = threading.Event(), threading.Event()

        def blocked(account_id):
            entered.set()
            if not release.wait(10):
                raise AssertionError('Teste não liberou a criação do cliente')
            return Client()

        self.factory.side_effect = blocked
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.call)
            self.assertTrue(entered.wait(10))
            try:
                self.assertEqual(self.call(), (200, {'status': 'busy'}))
            finally:
                release.set()
            self.assertEqual(first.result(), (200, {'status': 'idle'}))
        self.assertEqual(self.factory.call_count, 1)

    def test_factory_failure_is_sanitized_and_does_not_leave_active_lease(self):
        self.ready()
        self.factory.side_effect = ValueError('synthetic-token-do-not-print')
        status, data = self.call()
        self.assertEqual(status, 503)
        self.assertNotIn('synthetic-token', str(data))
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT lease_until FROM http_runtime').fetchone()[0], 0)
        self.assertEqual({r['state'] for r in self.store.agenda()}, {'queued'})

    def test_wrapper_delegates_existing_paths_with_untouched_environ(self):
        for path in ('/', '/healthz', '/api/state', '/internal/scheduler/tick', '/media/a.jpg', '/mcp'):
            env = {'PATH_INFO': path, 'REQUEST_METHOD': 'POST', 'wsgi.input': io.BytesIO(b'original')}
            result = [b'legacy-response']
            start = Mock()
            with patch('wsgi.application', return_value=result) as legacy, patch('stories.http.handle') as handler:
                self.assertIs(story_wsgi.application(env, start), result)
            self.assertIs(legacy.call_args.args[0], env)
            self.assertIs(legacy.call_args.args[1], start)
            handler.assert_not_called()

    def test_unconfigured_wrapper_fails_closed_without_reading_credentials(self):
        result = {}

        def start(status, headers):
            result.update(status=status, headers=dict(headers))

        with patch.dict(os.environ, {'ARTENOALTAR_STORIES_DIR': ''}), patch('stories.wsgi.client_factory') as factory:
            body = b''.join(story_wsgi.application(self.env, start))
        self.assertTrue(result['status'].startswith('503'))
        self.assertEqual(result['headers']['Cache-Control'], 'no-store')
        self.assertIn('error', json.loads(body))
        factory.assert_not_called()

    def test_wrapper_preserves_actual_existing_health_auth_and_finance_routes(self):
        with patch.object(app, 'DB', Path(self.temp.name)/'existing-test.db'), \
             patch.dict(os.environ, {'ARTENOALTAR_ORIGIN': 'https://gestao.example'}):
            app.initialize()

            def call(handler, path, data=None):
                raw = json.dumps(data or {}).encode()
                env = {'PATH_INFO': path, 'REQUEST_METHOD': 'GET' if data is None else 'POST',
                       'HTTP_HOST': 'gestao.example', 'HTTP_ORIGIN': 'https://gestao.example',
                       'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json', 'wsgi.input': io.BytesIO(raw)}
                result = {}
                def start(status, headers):
                    result.update(status=status, headers=headers)
                result['body'] = b''.join(handler(env, start))
                return result

            for path, data in [('/healthz', None), ('/api/state', None),
                               ('/api/transactions', {'description': 'Não autorizado', 'amount': 100})]:
                self.assertEqual(call(story_wsgi.application, path, data), call(existing_wsgi.application, path, data))
            with app.connect() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0], 0)
