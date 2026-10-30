"""Identificadores de conteúdo nunca reutilizados, inclusive após exclusão."""
from contextlib import contextmanager
import re

MAX_ID = (1 << 63)-1
REPLACEMENT = 'posts__monotonic_ids'
ID_DECLARATION = re.compile(
    r'(?P<prefix>[(,]\s*(?:id|"id"|`id`|\[id\])\s+INTEGER\s+PRIMARY\s+KEY)'
    r'(?P<ascending>\s+ASC)?(?P<automatic>\s+AUTOINCREMENT)?', re.IGNORECASE)


def _quoted(name):
    # Os nomes vêm do próprio catálogo SQLite; a citação mantém inclusive nomes
    # com espaços e aspas sem interpolá-los como código SQL.
    return '"'+name.replace('"', '""')+'"'


@contextmanager
def _atomic(conn, name):
    conn.execute('SAVEPOINT '+name)
    try:
        # Adquire o bloqueio de escrita antes de ler o maior identificador.
        # WHERE 0 não modifica linhas nem dispara triggers de conteúdo.
        conn.execute('UPDATE posts SET id=id WHERE 0')
        yield
    except BaseException:
        conn.execute('ROLLBACK TO '+name)
        conn.execute('RELEASE '+name)
        raise
    else:
        conn.execute('RELEASE '+name)


def _schema(conn):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='posts'").fetchone()
    if not row:
        raise ValueError('Inicialize a tabela de conteúdos antes de reservar identificadores.')
    sql = row[0]
    declaration = ID_DECLARATION.search(sql)
    if not declaration:
        raise ValueError('A tabela de conteúdos não possui identificador inteiro compatível.')
    return sql, declaration


def _historical_max(conn):
    greatest = max(0, conn.execute('SELECT COALESCE(MAX(id),0) FROM posts').fetchone()[0])
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for (name,) in tables:
        columns = conn.execute('PRAGMA table_info('+_quoted(name)+')').fetchall()
        if any(column[1] == 'post_id' for column in columns):
            value = conn.execute('SELECT COALESCE(MAX(post_id),0) FROM '+_quoted(name)+
                                 " WHERE typeof(post_id)='integer'").fetchone()[0]
            greatest = max(greatest, value)
    row = conn.execute("SELECT MAX(seq) FROM sqlite_sequence WHERE name='posts'").fetchone()
    if row and row[0] is not None:
        greatest = max(greatest, row[0])
    if type(greatest) is not int or greatest < 0 or greatest > MAX_ID:
        raise ValueError('Sequência de conteúdos inválida.')
    return greatest


def _seed(conn, value):
    if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name='posts'").fetchone():
        conn.execute("UPDATE sqlite_sequence SET seq=? WHERE name='posts'", (value,))
    else:
        conn.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('posts',?)", (value,))


def initialize(conn):
    """Migração atômica, preservando dados e objetos da tabela antiga."""
    original, declaration = _schema(conn)
    rebuilding = not declaration.group('automatic')
    foreign_keys = bool(conn.execute('PRAGMA foreign_keys').fetchone()[0])
    legacy_alter = bool(conn.execute('PRAGMA legacy_alter_table').fetchone()[0])
    # A troca não renomeia a tabela antiga: referências históricas continuam
    # apontando para posts. Não deixar DROP executar cascatas de chaves externas.
    restore_foreign_keys = rebuilding and foreign_keys and not conn.in_transaction
    if restore_foreign_keys:
        conn.execute('PRAGMA foreign_keys=OFF')
    try:
        with _atomic(conn, 'monotonic_posts_migration'):
            original, declaration = _schema(conn)
            if not declaration.group('automatic'):
                if foreign_keys and conn.in_transaction and not restore_foreign_keys:
                    # Não é possível mudar foreign_keys dentro de uma transação;
                    # uma recusa atômica é preferível a apagar referências.
                    raise ValueError('Conclua a transação antes da migração dos conteúdos.')
                statements = [row[0] for row in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE tbl_name='posts' AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type,name")]
                replacement = original[:declaration.end()]+ ' AUTOINCREMENT'+original[declaration.end():]
                replacement, count = re.subn(
                    r'^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:posts|"posts"|`posts`|\[posts\])(?=\s*\()',
                    'CREATE TABLE '+_quoted(REPLACEMENT), replacement, count=1, flags=re.IGNORECASE)
                if count != 1:
                    raise ValueError('A definição da tabela de conteúdos não pôde ser migrada.')
                conn.execute('PRAGMA legacy_alter_table=ON')
                conn.execute(replacement)
                columns = [row[1] for row in conn.execute('PRAGMA table_xinfo(posts)') if row[6] == 0]
                names = ','.join(map(_quoted, columns))
                conn.execute('INSERT INTO '+_quoted(REPLACEMENT)+' ('+names+') SELECT '+names+' FROM posts')
                conn.execute('DROP TABLE posts')
                conn.execute('ALTER TABLE '+_quoted(REPLACEMENT)+' RENAME TO posts')
                for statement in statements:
                    conn.execute(statement)
            _seed(conn, _historical_max(conn))
    finally:
        conn.execute('PRAGMA legacy_alter_table='+('ON' if legacy_alter else 'OFF'))
        if restore_foreign_keys:
            conn.execute('PRAGMA foreign_keys=ON')


def allocate(conn):
    """Reserva um ID novo dentro da transação do chamador, sem criar um post."""
    with _atomic(conn, 'monotonic_post_allocation'):
        _, declaration = _schema(conn)
        if not declaration.group('automatic'):
            raise ValueError('Inicialize a migração de conteúdos antes de reservar identificadores.')
        greatest = _historical_max(conn)
        if greatest == MAX_ID:
            raise ValueError('Não há identificadores de conteúdo disponíveis.')
        result = greatest+1
        _seed(conn, result)
        return result
