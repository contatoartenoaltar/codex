"""Receita vinculada ao pedido pago; cadastro e lançamento são atômicos."""
from datetime import date, datetime
from zoneinfo import ZoneInfo


def initialize(conn):
    columns = {row[1] for row in conn.execute('PRAGMA table_info(transactions)')}
    if 'order_id' not in columns:
        conn.execute('ALTER TABLE transactions ADD COLUMN order_id INTEGER')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS transactions_order ON transactions(order_id) WHERE order_id IS NOT NULL')


def today():
    return datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()


def income_description(order_id, customer, product):
    return f"Pedido #{order_id:04d} — {customer} — {product}"


def register_income(conn, order_id, day=None):
    """Chamado sob BEGIN IMMEDIATE, na mesma transação do cadastro/lançamento."""
    order = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if order is None:
        raise ValueError('Pedido não encontrado.')
    if order['status'] == 'Cancelado':
        raise ValueError('Não é possível lançar receita de um pedido cancelado.')
    existing = conn.execute('SELECT id,amount FROM transactions WHERE order_id=?', (order_id,)).fetchone()
    if existing:
        return {'id': existing['id'], 'amount': existing['amount'], 'created': False}
    if order['total'] == 0:
        return {'id': None, 'amount': 0, 'created': False}
    day = date.fromisoformat(day if day is not None else today()).isoformat()
    if day > today():
        raise ValueError('A data do recebimento não pode estar no futuro.')
    description = income_description(order_id, order['customer'], order['product'])
    cursor = conn.execute('''INSERT INTO transactions(description,kind,amount,date,order_id)
                             VALUES(?,'income',?,?,?)''', (description, order['total'], day, order_id))
    return {'id': cursor.lastrowid, 'amount': order['total'], 'created': True}


def delete_order(conn, order_id):
    """Exclui pedido e receita gerada por ele na mesma transação."""
    if conn.execute('SELECT 1 FROM orders WHERE id=?', (order_id,)).fetchone() is None:
        raise ValueError('Pedido não encontrado.')
    income = conn.execute('SELECT id FROM transactions WHERE order_id=?', (order_id,)).fetchone()
    conn.execute('DELETE FROM transactions WHERE order_id=?', (order_id,))
    conn.execute('DELETE FROM orders WHERE id=?', (order_id,))
    return {'income_deleted': income is not None}
