import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
import app
import auth
import http.cookiejar


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.tmp.name) / 'test.db'
        app.initialize()
        with app.connect() as c:
            auth.set_password(c, 'senha-de-teste-isolada')
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.post('login', {'password':'senha-de-teste-isolada'}, 200)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        app.DB = self.old_db
        self.tmp.cleanup()

    def post(self, endpoint, data, expected=201):
        request = urllib.request.Request(self.base+'/api/'+endpoint, data=json.dumps(data).encode(), headers={'Content-Type':'application/json', 'Origin':self.base})
        try:
            response = self.opener.open(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, expected)
            return json.load(response)

    def state(self):
        with self.opener.open(self.base+'/api/state') as response:
            return json.load(response)

    def test_financial_records_survive_database_reopen(self):
        self.post('transactions', {'description':'Envelopes vendidos','kind':'income','amount':22900,'date':'2026-10-29'})
        self.post('transactions', {'description':'Papel','kind':'expense','amount':5000,'date':'2026-10-29'})
        app.initialize()
        rows = self.state()['transactions']
        self.assertEqual(sum(r['amount']*(1 if r['kind']=='income' else -1) for r in rows), 17900)
        self.post('transactions', {'description':'Inválido','kind':'income','amount':-1,'date':'2026-10-29'}, 400)
        self.assertEqual(len(self.state()['transactions']), 2)

    def test_inventory_and_order_workflow(self):
        self.post('inventory', {'name':'Papel','unit':'folhas','quantity':500,'minimum':100})
        material = self.state()['inventory'][0]
        self.post('inventory/quantity', {'id':material['id'],'quantity':90})
        self.assertEqual(self.state()['inventory'][0]['quantity'], 90)
        self.post('orders', {'customer':'Igreja Teste','product':'envelopes','quantity':500,'total':22900,'notes':'Incluir logotipo'})
        order = self.state()['orders'][0]
        self.post('orders/status', {'id':order['id'],'status':'Em produção'})
        self.assertEqual(self.state()['orders'][0]['status'], 'Em produção')
        self.assertEqual(self.state()['transactions'], [])
        self.post('orders/status', {'id':order['id'],'status':'Inválido'}, 400)

    def test_commercial_rules_and_drafts(self):
        reply = self.post('reply', {'message':'Quanto custam 500 envelopes?'}, 200)['reply']
        self.assertIn('R$ 229,00', reply)
        reply = self.post('reply', {'message':'Qual o preço de 300 envelopes?'}, 200)['reply']
        self.assertIn('confirmação', reply)
        self.assertNotIn('R$', reply)
        reply = self.post('reply', {'message':'Entrega amanhã?'}, 200)['reply']
        self.assertIn('responsável', reply)
        self.post('posts', {'product':'envelopes','channel':'Instagram','use_ai':False})
        draft = self.state()['posts'][0]
        self.assertEqual(draft['source'], 'Modelo local')
        self.assertIn('16,2 × 11,4', draft['caption'])
        self.post('delete', {'table':'posts','id':draft['id']})
        self.assertEqual(self.state()['posts'], [])


    def test_authentication_logout_and_csrf(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base+'/api/state')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        request = urllib.request.Request(self.base+'/api/transactions', data=b'{}', headers={'Content-Type':'application/json','Origin':'https://other.example'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.opener.open(request)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.post('logout', {}, 200)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.state()
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.post('login', {'password':'senha-errada'}, 401)
        self.post('login', {'password':'senha-de-teste-isolada'}, 200)
        self.assertEqual(len(self.state()['products']), 8)

    def test_throttle_expiry_password_reset_and_backup(self):
        for _ in range(10):
            self.post('login', {'password':'errada'}, 401)
        self.post('login', {'password':'senha-de-teste-isolada'}, 429)
        with app.connect() as c:
            auth.set_password(c, 'nova-senha-de-teste')
        self.post('transactions', {}, 401)
        self.post('login', {'password':'nova-senha-de-teste'}, 200)
        with app.connect() as c:
            c.execute('UPDATE sessions SET expires=0')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.state()
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.post('login', {'password':'nova-senha-de-teste'}, 200)
        self.post('transactions', {'description':'Backup','kind':'income','amount':9900,'date':'2026-10-29'})
        import backup, sqlite3
        destination = Path(self.tmp.name) / 'backup.db'
        backup.backup(destination)
        with sqlite3.connect(destination) as c:
            self.assertEqual(c.execute('SELECT amount FROM transactions').fetchone()[0], 9900)
        with self.assertRaises(FileExistsError):
            backup.backup(destination)

    def test_catalog_and_static_app(self):
        self.assertEqual(len(self.state()['products']), 8)
        self.assertEqual(self.state()['products'][0]['prices']['1000'], 39900)
        for path, expected in [('/', b'Arte no Altar'), ('/app.js', b'dashboard'), ('/style.css', b'@media')]:
            with self.opener.open(self.base+path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(expected, response.read())


if __name__ == '__main__':
    unittest.main()
