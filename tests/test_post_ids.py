from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

import app
import post_ids


def create_legacy(conn):
    conn.executescript('''
        CREATE TABLE posts (id INTEGER PRIMARY KEY, product TEXT NOT NULL,
            channel TEXT NOT NULL, caption TEXT NOT NULL, source TEXT NOT NULL);
        CREATE TABLE business (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO business VALUES (1,'preservar');
    ''')


def add_post(conn, caption='Legenda'):
    return conn.execute("INSERT INTO posts(product,channel,caption,source) VALUES('Produto','Instagram',?,'Teste')",
                        (caption,)).lastrowid


class FailingConnection(sqlite3.Connection):
    fail_rename = False

    def execute(self, sql, parameters=(), /):
        if self.fail_rename and sql.startswith('ALTER TABLE "posts__monotonic_ids"'):
            raise sqlite3.OperationalError('interrupção simulada')
        return super().execute(sql, parameters)


class PostIdTests(unittest.TestCase):
    def test_application_never_reuses_deleted_highest_id_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = app.DB
            try:
                app.DB = Path(directory)/'app.db'
                app.initialize()
                with app.connect() as conn:
                    first = add_post(conn, 'Primeiro')
                    removed = add_post(conn, 'Excluído')
                    conn.execute('DELETE FROM posts WHERE id=?', (removed,))
                app.initialize()
                with app.connect() as conn:
                    new = add_post(conn, 'Novo')
                    self.assertGreater(new, removed)
                    self.assertEqual(conn.execute('SELECT caption FROM posts WHERE id=?', (first,)).fetchone()[0], 'Primeiro')
            finally:
                app.DB = previous

    def test_every_post_history_table_reserves_its_deleted_identifiers(self):
        references = ['post_schedule', 'publication_attempts', 'publication_staged_media',
                      'feed_compositions', 'feed_auto_slots', 'social_mcp_operations',
                      'social_mcp_schedule_operations', 'future_content_history']
        for name in references:
            with self.subTest(table=name), sqlite3.connect(':memory:') as conn:
                create_legacy(conn)
                conn.execute('CREATE TABLE '+name+' (post_id INTEGER NOT NULL)')
                conn.execute('INSERT INTO '+name+' VALUES(900)')
                post_ids.initialize(conn)
                self.assertGreater(add_post(conn), 900)
                self.assertEqual(conn.execute('SELECT post_id FROM '+name).fetchone()[0], 900)
                self.assertEqual(conn.execute('SELECT value FROM business').fetchone()[0], 'preservar')

    def test_migration_preserves_all_columns_values_indexes_triggers_and_views(self):
        with sqlite3.connect(':memory:') as conn:
            create_legacy(conn)
            conn.executescript('''
                ALTER TABLE posts ADD COLUMN image_name TEXT NOT NULL DEFAULT '';
                ALTER TABLE posts ADD COLUMN account_id TEXT NOT NULL DEFAULT '';
                ALTER TABLE posts ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE posts ADD COLUMN custom_blob BLOB;
                ALTER TABLE posts ADD COLUMN custom_number REAL;
                ALTER TABLE posts ADD COLUMN caption_length INTEGER GENERATED ALWAYS AS (length(caption)) VIRTUAL;
                CREATE INDEX posts_account ON posts(account_id) WHERE revision>0;
                CREATE TABLE audit (content_id INTEGER, caption TEXT);
                CREATE TRIGGER posts_caption AFTER UPDATE OF caption ON posts BEGIN
                    INSERT INTO audit VALUES(new.id,new.caption);
                END;
                CREATE VIEW content_titles AS SELECT id,caption FROM posts;
            ''')
            conn.execute('''INSERT INTO posts(id,product,channel,caption,source,image_name,
                                account_id,revision,custom_blob,custom_number)
                VALUES(7,'Envelope','Instagram','Olá, igreja!','Teste','arte.jpg','123',4,?,3.5)''',
                         (b'\x00\xffconteudo',))
            before = conn.execute('SELECT * FROM posts').fetchall()
            columns = conn.execute('PRAGMA table_xinfo(posts)').fetchall()
            objects = conn.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='posts' AND type IN ('index','trigger') ORDER BY name").fetchall()
            post_ids.initialize(conn)
            self.assertEqual(conn.execute('SELECT * FROM posts').fetchall(), before)
            self.assertEqual(conn.execute('PRAGMA table_xinfo(posts)').fetchall(), columns)
            self.assertEqual(conn.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='posts' AND type IN ('index','trigger') ORDER BY name").fetchall(), objects)
            self.assertEqual(conn.execute('SELECT * FROM content_titles').fetchall(), [(7, 'Olá, igreja!')])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM audit').fetchone()[0], 0)
            conn.execute("UPDATE posts SET caption='Atualizada' WHERE id=7")
            self.assertEqual(conn.execute('SELECT * FROM audit').fetchall(), [(7, 'Atualizada')])
            self.assertGreater(add_post(conn), 7)

    def test_failure_rolls_back_table_rebuild_and_preserves_other_data(self):
        conn = sqlite3.connect(':memory:', factory=FailingConnection)
        try:
            create_legacy(conn)
            add_post(conn)
            conn.commit()
            before = list(conn.iterdump())
            conn.fail_rename = True
            with self.assertRaises(sqlite3.OperationalError):
                post_ids.initialize(conn)
            self.assertEqual(list(conn.iterdump()), before)
            self.assertFalse(conn.in_transaction)
            conn.fail_rename = False
            post_ids.initialize(conn)
            self.assertGreater(add_post(conn), 1)
        finally:
            conn.close()

    def test_failure_does_not_rollback_or_commit_callers_transaction(self):
        conn = sqlite3.connect(':memory:', factory=FailingConnection)
        try:
            create_legacy(conn)
            conn.execute("UPDATE business SET value='transação externa' WHERE id=1")
            conn.fail_rename = True
            with self.assertRaises(sqlite3.OperationalError):
                post_ids.initialize(conn)
            self.assertTrue(conn.in_transaction)
            self.assertEqual(conn.execute('SELECT value FROM business').fetchone()[0], 'transação externa')
            conn.rollback()
            self.assertEqual(conn.execute('SELECT value FROM business').fetchone()[0], 'preservar')
        finally:
            conn.close()

    def test_migration_preserves_foreign_key_references_and_setting(self):
        with sqlite3.connect(':memory:') as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            create_legacy(conn)
            conn.executescript('''
                INSERT INTO posts VALUES(3,'Produto','Instagram','Legenda','Teste');
                CREATE TABLE child (post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE);
                INSERT INTO child VALUES(3);
            ''')
            post_ids.initialize(conn)
            self.assertEqual(conn.execute('SELECT * FROM child').fetchall(), [(3,)])
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_reinitialization_preserves_sequence_after_all_posts_are_deleted(self):
        with sqlite3.connect(':memory:') as conn:
            create_legacy(conn)
            conn.execute("INSERT INTO posts VALUES(100,'Produto','Instagram','Legenda','Teste')")
            post_ids.initialize(conn)
            conn.execute('DELETE FROM posts')
            post_ids.initialize(conn)
            post_ids.initialize(conn)
            self.assertEqual(add_post(conn), 101)

    def test_nonpositive_legacy_ids_are_preserved_without_reusing_them(self):
        with sqlite3.connect(':memory:') as conn:
            create_legacy(conn)
            conn.execute("INSERT INTO posts VALUES(-3,'Produto','Instagram','Legenda','Teste')")
            post_ids.initialize(conn)
            self.assertEqual(conn.execute('SELECT id FROM posts').fetchone()[0], -3)
            self.assertEqual(add_post(conn), 1)

    def test_allocator_reserves_unique_ids_above_all_history_and_native_inserts(self):
        with sqlite3.connect(':memory:') as conn:
            create_legacy(conn)
            post_ids.initialize(conn)
            first = post_ids.allocate(conn)
            second = post_ids.allocate(conn)
            self.assertGreater(second, first)
            native = add_post(conn)
            self.assertGreater(native, second)
            conn.execute('CREATE TABLE future_history (post_id INTEGER)')
            conn.execute('INSERT INTO future_history VALUES(700)')
            reserved = post_ids.allocate(conn)
            self.assertEqual(reserved, 701)
            conn.execute('UPDATE posts SET id=? WHERE id=?', (reserved, native))
            self.assertEqual(add_post(conn), 702)

    def test_allocator_is_atomic_with_the_callers_transaction(self):
        with sqlite3.connect(':memory:') as conn:
            create_legacy(conn)
            post_ids.initialize(conn)
            conn.execute('BEGIN')
            first = post_ids.allocate(conn)
            conn.rollback()
            self.assertEqual(post_ids.allocate(conn), first)

    def test_concurrent_allocations_are_unique_even_without_inserting_posts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'ids.db')
            with sqlite3.connect(path) as conn:
                create_legacy(conn)
                post_ids.initialize(conn)
            def reserve(_):
                with sqlite3.connect(path) as conn:
                    return post_ids.allocate(conn)
            with ThreadPoolExecutor(max_workers=4) as executor:
                identifiers = list(executor.map(reserve, range(16)))
            self.assertEqual(len(set(identifiers)), 16)
            self.assertEqual(sorted(identifiers), list(range(1, 17)))
            with sqlite3.connect(path) as conn:
                self.assertEqual(add_post(conn), 17)


if __name__ == '__main__':
    unittest.main()
