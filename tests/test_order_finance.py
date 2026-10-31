import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import app
import auth
import order_finance
import wsgi


class OrderFinanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = Path(self.tmp.name) / 'orders.db'
        app.initialize()
        self.env = patch.dict(os.environ, {'ARTENOALTAR_ORIGIN': 'https://gestao.example'})
        self.env.start()
        self.clock = patch('order_finance.today', return_value='2026-10-30')
        self.clock.start()
        with app.connect() as conn:
            auth.set_password(conn, 'senha-isolada-pedidos')
        login = self.call('/api/login', {'password': 'senha-isolada-pedidos'})
        self.cookie = login['headers']['Set-Cookie'].split(';')[0]

    def tearDown(self):
        self.clock.stop()
        self.env.stop()
        app.DB = self.old_db
        self.tmp.cleanup()

    def call(self, path, data=None, cookie=None, origin='https://gestao.example'):
        body = json.dumps(data or {}).encode()
        env = {'PATH_INFO': path, 'REQUEST_METHOD': 'GET' if data is None else 'POST',
               'HTTP_HOST': 'gestao.example', 'HTTP_ORIGIN': origin,
               'HTTP_COOKIE': getattr(self, 'cookie', '') if cookie is None else cookie,
               'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
        result = {}

        def start(status, headers):
            result.update(status=int(status.split()[0]), headers=dict(headers))

        result['data'] = json.loads(b''.join(wsgi.application(env, start)))
        return result

    def post(self, path, data, status=201):
        response = self.call('/api/' + path, data)
        self.assertEqual(response['status'], status, response['data'])
        return response['data']

    def state(self):
        return self.call('/api/state')['data']

    def create(self, total=39900):
        return self.post('orders', {'customer': 'Igreja Teste', 'product': 'envelopes',
                                    'quantity': 1000, 'total': total, 'notes': 'Pedido real'})

    def legacy_order(self, status='Concluído', total=14900):
        with app.connect() as conn:
            return conn.execute('''INSERT INTO orders(customer,product,quantity,total,status,notes)
                VALUES('Cliente antigo','Envelopes personalizados',200,?,?, 'Preservar')''',
                (total, status)).lastrowid

    def test_new_order_immediately_registers_exact_income_and_survives_reload(self):
        saved = self.create()
        state = self.state()
        order, income = state['orders'][0], state['transactions'][0]
        self.assertEqual(order['status'], 'Novo')
        self.assertEqual(order['notes'], 'Pedido real')
        self.assertEqual(order['transaction_id'], income['id'])
        self.assertEqual((income['kind'], income['amount'], income['date'], income['order_id']),
                         ('income', 39900, '2026-10-30', saved['id']))
        self.assertIn(f"#{saved['id']:04d}", income['description'])
        self.assertIn('Igreja Teste', income['description'])
        self.assertTrue(saved['income']['created'])
        app.initialize()
        self.assertEqual(self.state()['transactions'], state['transactions'])

    def test_production_completion_cancellation_and_reopening_never_duplicate_or_refund(self):
        saved = self.create()
        income = self.state()['transactions']
        for stage in ['Em produção', 'Concluído', 'Concluído', 'Cancelado', 'Novo', 'Concluído']:
            self.post('orders/status', {'id': saved['id'], 'status': stage})
            self.assertEqual(self.state()['transactions'], income)
        again = self.post('orders/income', {'id': saved['id'], 'date': '2026-10-29'})
        self.assertFalse(again['income']['created'])
        self.assertEqual(self.state()['transactions'], income)

    def test_historical_orders_are_not_backfilled_on_reload_or_stage_change(self):
        old = self.legacy_order()
        self.post('transactions', {'description': 'Recebimento manual', 'kind': 'income',
                                   'amount': 9900, 'date': '2026-10-28'})
        manual = self.state()['transactions'][0]
        app.initialize()
        self.post('orders/status', {'id': old, 'status': 'Concluído'})
        self.assertEqual(self.state()['transactions'], [manual])
        self.assertIsNone(self.state()['orders'][0]['transaction_id'])
        result = self.post('orders/income', {'id': old, 'date': '2026-10-29',
                                            'amount': 1, 'kind': 'expense'})
        self.assertTrue(result['income']['created'])
        received = self.state()['transactions'][0]
        self.assertEqual((received['amount'], received['date'], received['kind']),
                         (14900, '2026-10-29', 'income'))
        self.assertEqual(self.state()['transactions'][1], manual)
        new_stage = self.legacy_order('Novo')
        self.post('orders/income', {'id': new_stage, 'date': '2026-10-30'})
        self.assertEqual(self.state()['orders'][0]['status'], 'Novo')

    def test_failed_income_rolls_back_new_order_and_manual_records_are_preserved(self):
        self.post('transactions', {'description': 'Papel', 'kind': 'expense',
                                   'amount': 5000, 'date': '2026-10-28'})
        manual = self.state()['transactions']
        with app.connect() as conn:
            conn.execute('''CREATE TRIGGER reject_order_income BEFORE INSERT ON transactions
                WHEN NEW.order_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'falha de teste'); END''')
        self.post('orders', {'customer': 'Teste', 'product': 'envelopes',
                             'quantity': 100, 'total': 9900}, 500)
        self.assertEqual(self.state()['orders'], [])
        self.assertEqual(self.state()['transactions'], manual)

    def test_simultaneous_receipts_for_same_legacy_order_create_only_one_income(self):
        old = self.legacy_order()
        barrier = threading.Barrier(2)

        def receive(_):
            barrier.wait(timeout=5)
            return self.call('/api/orders/income', {'id': old, 'date': '2026-10-30'})

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(receive, range(2)))
        self.assertEqual([r['status'] for r in results], [201, 201])
        self.assertEqual(sum(r['data']['income']['created'] for r in results), 1)
        self.assertEqual(len(self.state()['transactions']), 1)

    def test_linked_order_cannot_be_deleted_and_its_id_reused_for_another_customer(self):
        saved = self.create()
        before = self.state()
        self.post('delete', {'table': 'orders', 'id': saved['id']}, 400)
        self.assertEqual(self.state()['orders'], before['orders'])
        self.assertEqual(self.state()['transactions'], before['transactions'])
        self.post('delete', {'table': 'transactions', 'id': saved['income']['id']})
        self.assertIsNone(self.state()['orders'][0]['transaction_id'])
        app.initialize()
        self.assertEqual(self.state()['transactions'], [])
        self.post('delete', {'table': 'orders', 'id': saved['id']})
        self.create(total=9900)
        self.assertEqual(len(self.state()['transactions']), 1)
        self.assertEqual(self.state()['transactions'][0]['amount'], 9900)

    def test_legacy_schema_upgrade_preserves_every_existing_record_without_guessing_links(self):
        app.DB = Path(self.tmp.name) / 'legacy.db'
        with sqlite3.connect(app.DB) as conn:
            conn.executescript('''
                CREATE TABLE transactions(id INTEGER PRIMARY KEY,description TEXT NOT NULL,
                    kind TEXT NOT NULL,amount INTEGER NOT NULL,date TEXT NOT NULL);
                CREATE TABLE orders(id INTEGER PRIMARY KEY,customer TEXT NOT NULL,product TEXT NOT NULL,
                    quantity INTEGER NOT NULL,total INTEGER NOT NULL,status TEXT NOT NULL,notes TEXT NOT NULL);
                INSERT INTO transactions VALUES(7,'Entrada anterior','income',22900,'2026-10-29');
                INSERT INTO transactions VALUES(8,'Papel','expense',5000,'2026-10-29');
                INSERT INTO orders VALUES(3,'Cliente anterior','Envelopes',500,22900,'Concluído','Original');
            ''')
        app.initialize()
        app.initialize()
        with app.connect() as conn:
            rows = [tuple(r) for r in conn.execute('SELECT * FROM transactions ORDER BY id')]
            self.assertEqual(rows, [(7, 'Entrada anterior', 'income', 22900, '2026-10-29', None),
                                    (8, 'Papel', 'expense', 5000, '2026-10-29', None)])
            self.assertEqual(tuple(conn.execute('SELECT * FROM orders').fetchone()),
                             (3, 'Cliente anterior', 'Envelopes', 500, 22900, 'Concluído', 'Original'))

    def test_validation_and_auth_do_not_create_payments(self):
        old = self.legacy_order()
        canceled = self.legacy_order('Cancelado')
        for data in [{'id': old, 'date': '2026-10-31'}, {'id': old, 'date': '2026-02-30'},
                     {'id': canceled, 'date': '2026-10-30'}, {'id': 9999, 'date': '2026-10-30'},
                     {'id': True, 'date': '2026-10-30'}, {'id': old}]:
            self.post('orders/income', data, 400)
        for path in ['/api/orders', '/api/orders/income', '/api/orders/status']:
            self.assertEqual(self.call(path, {}, cookie='')['status'], 401)
            self.assertEqual(self.call(path, {}, origin='https://externo.example')['status'], 403)
        self.post('orders/status', {'id': old, 'status': 'Inválido'}, 400)
        self.assertEqual(self.state()['transactions'], [])
        self.assertEqual(self.state()['orders'][1]['status'], 'Concluído')

    def test_zero_value_order_does_not_create_a_zero_income(self):
        saved = self.create(total=0)
        self.assertIsNone(saved['income']['id'])
        self.assertEqual(self.state()['transactions'], [])
        self.assertEqual(self.state()['orders'][0]['status'], 'Novo')


class BusinessDateTests(unittest.TestCase):
    def test_income_date_uses_sao_paulo_even_after_utc_midnight(self):
        real_datetime = datetime

        class Clock:
            @staticmethod
            def now(zone):
                return real_datetime(2026, 10, 31, 1, 30, tzinfo=timezone.utc).astimezone(zone)

        with patch('order_finance.datetime', Clock):
            self.assertEqual(order_finance.today(), '2026-10-30')
