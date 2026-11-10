"""Recebimentos integrais ou parciais vinculados aos pedidos."""
from datetime import date, datetime
from zoneinfo import ZoneInfo


def initialize(conn):
    columns = {row[1] for row in conn.execute('PRAGMA table_info(transactions)')}
    if 'order_id' not in columns:
        conn.execute('ALTER TABLE transactions ADD COLUMN order_id INTEGER')
    # Versões anteriores permitiam uma única receita por pedido. Um pedido
    # parcelado precisa de vários recebimentos, preservando os registros antigos.
    conn.execute('DROP INDEX IF EXISTS transactions_order')
    conn.execute('''CREATE INDEX IF NOT EXISTS transactions_order_lookup
                    ON transactions(order_id) WHERE order_id IS NOT NULL''')


def today():
    return datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()


def income_description(order_id, customer, product):
    return f"Pedido #{order_id:04d} — {customer} — {product}"


def payment_summary(conn, order_id):
    row = conn.execute('''SELECT COUNT(*) AS payment_count,
                                 COALESCE(SUM(amount), 0) AS received_amount,
                                 MAX(id) AS transaction_id
                          FROM transactions
                          WHERE order_id=? AND kind='income' ''', (order_id,)).fetchone()
    return {
        'payment_count': row['payment_count'],
        'received_amount': row['received_amount'],
        'transaction_id': row['transaction_id'],
    }


def register_income(conn, order_id, day=None, amount=None):
    """Chamado sob BEGIN IMMEDIATE, na mesma transação do cadastro/lançamento."""
    order = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if order is None:
        raise ValueError('Pedido não encontrado.')
    if order['status'] == 'Cancelado':
        raise ValueError('Não é possível lançar receita de um pedido cancelado.')
    if order['total'] == 0:
        if amount is not None:
            raise ValueError('Não é possível registrar receita parcial em um pedido sem valor.')
        return {'id': None, 'amount': 0, 'created': False}
    summary = payment_summary(conn, order_id)
    remaining = order['total'] - summary['received_amount']
    if remaining <= 0:
        return {'id': summary['transaction_id'], 'amount': 0, 'created': False,
                'received_amount': summary['received_amount'], 'remaining_amount': 0}
    if amount is None:
        amount = remaining
        partial = False
    else:
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ValueError('Informe um valor parcial maior que zero.')
        if amount > remaining:
            raise ValueError('O valor recebido não pode ultrapassar o saldo restante do pedido.')
        partial = True
    day = date.fromisoformat(day if day is not None else today()).isoformat()
    if day > today():
        raise ValueError('A data do recebimento não pode estar no futuro.')
    description = income_description(order_id, order['customer'], order['product'])
    if partial:
        description += ' — Receita parcial'
    cursor = conn.execute('''INSERT INTO transactions(description,kind,amount,date,order_id)
                             VALUES(?,'income',?,?,?)''', (description, amount, day, order_id))
    received = summary['received_amount'] + amount
    return {'id': cursor.lastrowid, 'amount': amount, 'created': True,
            'received_amount': received, 'remaining_amount': order['total'] - received}


def delete_order(conn, order_id):
    """Exclui pedido e receita gerada por ele na mesma transação."""
    if conn.execute('SELECT 1 FROM orders WHERE id=?', (order_id,)).fetchone() is None:
        raise ValueError('Pedido não encontrado.')
    income = conn.execute('SELECT id FROM transactions WHERE order_id=?', (order_id,)).fetchone()
    conn.execute('DELETE FROM transactions WHERE order_id=?', (order_id,))
    conn.execute('DELETE FROM orders WHERE id=?', (order_id,))
    return {'income_deleted': income is not None}
