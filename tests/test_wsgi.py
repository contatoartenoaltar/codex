import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import auth
import wsgi
import backup


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / 'production.db'
        app.initialize()
        with app.connect() as c:
            auth.set_password(c, 'senha-isolada-producao')
        self.env = patch.dict(os.environ, {'ARTENOALTAR_ORIGIN':'https://gestao.example'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        app.DB = self.old_db
        self.temp.cleanup()

    def call(self, path, method='GET', data=None, cookie='', origin='https://gestao.example'):
        content = json.dumps(data or {}).encode()
        environ = {'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_HOST':'gestao.example','HTTP_ORIGIN':origin,'HTTP_COOKIE':cookie,'CONTENT_LENGTH':str(len(content)),'wsgi.input':io.BytesIO(content)}
        result = {}
        def start(status, headers):
            result['status'] = int(status.split()[0])
            result['headers'] = dict(headers)
        result['body'] = b''.join(wsgi.application(environ,start))
        return result

    def test_production_session_headers_and_database(self):
        self.assertEqual(self.call('/api/state')['status'], 401)
        self.assertIn(b'login-form', self.call('/')['body'])
        response = self.call('/api/login','POST',{'password':'senha-isolada-producao'})
        self.assertEqual(response['status'], 200)
        cookie = response['headers']['Set-Cookie']
        for flag in ['HttpOnly','SameSite=Strict','Secure']:
            self.assertIn(flag,cookie)
        self.assertIn('max-age=',response['headers']['Strict-Transport-Security'])
        cookie = cookie.split(';')[0]
        self.assertIn(b'id="view"', self.call('/',cookie=cookie)['body'])
        response = self.call('/api/transactions','POST',{'kind':'income','amount':22900,'description':'Teste','date':'2026-10-29'},cookie)
        self.assertEqual(response['status'],201)
        self.assertEqual(self.call('/api/delete','POST',{'table':'transactions','id':1},cookie,origin='https://externo.example')['status'],403)
        self.assertEqual(self.call('/api/logout','POST',{},cookie)['status'],200)
        self.assertEqual(self.call('/api/state',cookie=cookie)['status'],401)

    def test_backup_restores_login_and_records(self):
        with app.connect() as c:
            c.execute("INSERT INTO inventory(name,unit,quantity,minimum) VALUES('Papel','folhas',200,50)")
        destination = Path(self.temp.name) / 'backup.db'
        backup.backup(destination)
        app.DB = destination
        app.initialize()
        with app.connect() as c:
            token, error, status = auth.login(c,'senha-isolada-producao')
            self.assertEqual(status,200)
            self.assertIsNone(error)
            self.assertEqual(c.execute('SELECT quantity FROM inventory').fetchone()[0],200)

    def test_health_and_method(self):
        self.assertEqual(json.loads(self.call('/healthz')['body']), {'ok':True})
        self.assertEqual(self.call('/api/state','DELETE')['status'],405)
        chart=self.call('/dashboard-chart.js')
        self.assertEqual(chart['status'],200)
        self.assertEqual(chart['headers']['Content-Type'],'text/javascript')

    def test_stale_browser_cannot_cancel_a_new_schedule(self):
        login=self.call('/api/login','POST',{'password':'senha-isolada-producao'})
        cookie=login['headers']['Set-Cookie'].split(';')[0]
        with app.connect() as c:
            c.execute("INSERT INTO posts(id,product,channel,caption,source,publish_status,revision) VALUES(1,'Envelope','Instagram','Aprovada','Teste','scheduled',1)")
            c.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(1,1,1800000000,'queued')")
        for data in [{'id':1}, {'id':1,'revision':0,'expected_due_at':1799999900}]:
            self.assertEqual(self.call('/api/posts/cancel-schedule','POST',data,cookie)['status'],400)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT state FROM post_schedule').fetchone()[0],'queued')
        self.assertEqual(self.call('/api/posts/cancel-schedule','POST',
            {'id':1,'revision':1,'expected_due_at':1800000000},cookie)['status'],200)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT publish_status,revision FROM posts').fetchone()[:],('draft',2))
