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

    def test_transaction_notes_survive_reload_without_changing_financial_values(self):
        notes = 'Fornecedor: Papel & Cia\nReferência: <nota 123> — à vista'
        for kind in ('income', 'expense'):
            self.post('transactions', {'description': 'Lançamento', 'kind': kind,
                                     'amount': 12345, 'date': '2026-10-29', 'notes': notes})
        before = self.state()['transactions']
        app.initialize()
        self.assertEqual(self.state()['transactions'], before)
        self.assertEqual({r['kind'] for r in before}, {'income', 'expense'})
        for row in before:
            self.assertEqual(row['notes'], notes)
            self.assertEqual(row['amount'], 12345)
            self.assertEqual(row['description'], 'Lançamento')

    def test_expense_can_be_edited_without_changing_its_kind(self):
        self.post('transactions', {'description': 'Papel', 'kind': 'expense',
                                   'amount': 5000, 'date': '2026-10-29',
                                   'notes': 'Compra inicial'})
        expense = self.state()['transactions'][0]
        self.post('transactions/update', {'id': expense['id'], 'description': 'Papel especial',
                                          'amount': 6500, 'date': '2026-10-30',
                                          'notes': 'Valor corrigido'}, 200)
        updated = self.state()['transactions'][0]
        self.assertEqual((updated['description'], updated['kind'], updated['amount'],
                          updated['date'], updated['notes']),
                         ('Papel especial', 'expense', 6500, '2026-10-30', 'Valor corrigido'))

    def test_expense_edit_rejects_other_kinds_and_invalid_data_without_changes(self):
        for kind in ('income', 'investment'):
            self.post('transactions', {'description': kind, 'kind': kind,
                                       'amount': 1000, 'date': '2026-10-29'})
        before = self.state()['transactions']
        for transaction in before:
            self.post('transactions/update', {'id': transaction['id'], 'description': 'Alterado',
                                              'amount': 2000, 'date': '2026-10-30', 'notes': ''}, 400)
        self.post('transactions/update', {'id': 999, 'description': 'Inexistente',
                                          'amount': 2000, 'date': '2026-10-30', 'notes': ''}, 400)
        self.assertEqual(self.state()['transactions'], before)

    def test_transaction_notes_are_optional_bounded_and_validated_before_writing(self):
        data = {'description': 'Papel', 'kind': 'expense', 'amount': 5000, 'date': '2026-10-29'}
        self.post('transactions', data)
        self.assertEqual(self.state()['transactions'][0]['notes'], '')
        self.post('transactions', data | {'notes': 'á' * 3000})
        before = self.state()['transactions']
        for notes in (None, 42, [], {}, 'a' * 3001):
            self.post('transactions', data | {'notes': notes}, 400)
            self.assertEqual(self.state()['transactions'], before)

    def test_transaction_notes_do_not_bypass_authentication_or_origin_checks(self):
        data = {'description': 'Papel', 'kind': 'expense', 'amount': 5000,
                'date': '2026-10-29', 'notes': 'Detalhes privados'}
        self.assertEqual(self.call('/api/transactions', data, cookie='')['status'], 401)
        self.assertEqual(self.call('/api/transactions', data, origin='https://externo.example')['status'], 403)
        self.assertEqual(self.state()['transactions'], [])

    def test_production_completion_cancellation_and_reopening_never_duplicate_or_refund(self):
        saved = self.create()
        income = self.state()['transactions']
        for stage in ['Em produção', 'Concluído', 'Concluído', 'Cancelado', 'Novo', 'Concluído']:
            self.post('orders/status', {'id': saved['id'], 'status': stage})
            self.assertEqual(self.state()['transactions'], income)
        again = self.post('orders/income', {'id': saved['id'], 'date': '2026-10-29'})
        self.assertFalse(again['income']['created'])
        self.assertEqual(self.state()['transactions'], income)

    def test_editing_order_updates_linked_income_without_creating_another_record(self):
        saved = self.create()
        before = self.state()['transactions'][0]
        result = self.post('orders/update', {
            'id': saved['id'], 'customer': 'Igreja Corrigida', 'product': 'calendarios',
            'quantity': 250, 'total': 27500, 'notes': 'Nova observação'
        }, 200)
        self.assertTrue(result['ok'])
        state = self.state()
        order = state['orders'][0]
        self.assertEqual((order['customer'], order['product'], order['quantity'], order['total'],
                          order['status'], order['notes']),
                         ('Igreja Corrigida', 'Calendários personalizados', 250, 27500,
                          'Novo', 'Nova observação'))
        self.assertEqual(len(state['transactions']), 1)
        income = state['transactions'][0]
        self.assertEqual((income['id'], income['kind'], income['amount'], income['date'],
                          income['order_id']),
                         (before['id'], 'income', 27500, before['date'], saved['id']))
        self.assertIn('Igreja Corrigida', income['description'])
        self.assertIn('Calendários personalizados', income['description'])

    def test_editing_order_without_income_preserves_legacy_product_and_creates_no_income(self):
        old = self.legacy_order(total=14900)
        self.post('orders/update', {
            'id': old, 'customer': 'Cliente corrigido', 'product': '__current__',
            'quantity': 300, 'total': 19900, 'notes': 'Corrigido'
        }, 200)
        state = self.state()
        self.assertEqual(state['transactions'], [])
        self.assertEqual((state['orders'][0]['product'], state['orders'][0]['total']),
                         ('Envelopes personalizados', 19900))

    def test_order_edit_is_atomic_and_validated(self):
        saved = self.create()
        before = self.state()
        invalid = [
            {'id': saved['id'], 'customer': 'Igreja', 'product': 'envelopes',
             'quantity': 100, 'total': 0, 'notes': ''},
            {'id': saved['id'], 'customer': '', 'product': 'envelopes',
             'quantity': 100, 'total': 9900, 'notes': ''},
            {'id': saved['id'], 'customer': 'Igreja', 'product': 'inexistente',
             'quantity': 100, 'total': 9900, 'notes': ''},
            {'id': 9999, 'customer': 'Igreja', 'product': 'envelopes',
             'quantity': 100, 'total': 9900, 'notes': ''},
        ]
        for data in invalid:
            self.post('orders/update', data, 400)
            self.assertEqual(self.state(), before)
        data = {'id': saved['id'], 'customer': 'Igreja', 'product': 'envelopes',
                'quantity': 100, 'total': 9900, 'notes': ''}
        self.assertEqual(self.call('/api/orders/update', data, cookie='')['status'], 401)
        self.assertEqual(self.call('/api/orders/update', data,
                                   origin='https://externo.example')['status'], 403)
        self.assertEqual(self.state(), before)

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

    def test_linked_order_and_its_income_are_deleted_atomically(self):
        saved = self.create()
        self.post('delete', {'table': 'orders', 'id': saved['id']})
        self.assertEqual(self.state()['orders'], [])
        self.assertEqual(self.state()['transactions'], [])
        app.initialize()
        replacement = self.create(total=9900)
        state = self.state()
        self.assertEqual(len(state['transactions']), 1)
        self.assertEqual(state['transactions'][0]['amount'], 9900)
        self.assertEqual(state['transactions'][0]['order_id'], replacement['id'])

    def test_order_deletion_rolls_back_if_linked_income_cannot_be_deleted(self):
        saved = self.create()
        before = self.state()
        with app.connect() as conn:
            conn.execute('''CREATE TRIGGER reject_income_delete BEFORE DELETE ON transactions
                WHEN OLD.order_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'falha de teste'); END''')
        self.post('delete', {'table': 'orders', 'id': saved['id']}, 500)
        self.assertEqual(self.state()['orders'], before['orders'])
        self.assertEqual(self.state()['transactions'], before['transactions'])

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
            rows = [tuple(r) for r in conn.execute('SELECT id,description,kind,amount,date,order_id FROM transactions ORDER BY id')]
            self.assertEqual(rows, [(7, 'Entrada anterior', 'income', 22900, '2026-10-29', None),
                                    (8, 'Papel', 'expense', 5000, '2026-10-29', None)])
            self.assertEqual([r[0] for r in conn.execute('SELECT notes FROM transactions')], ['', ''])
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
