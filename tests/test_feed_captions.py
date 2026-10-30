"""Caption replacement preserves the approved artwork and queued publication."""
import sqlite3
import unittest
from unittest.mock import patch

import app
import drive_source as drive
import feed_autonomy as auto
import feed_composer as composer
import tests.test_feed_autonomy as fixtures


class FeedCaptionTests(unittest.TestCase):
    setUp = fixtures.FeedAutonomyTests.setUp
    tearDown = fixtures.FeedAutonomyTests.tearDown
    heartbeat = fixtures.FeedAutonomyTests.heartbeat

    def queue(self, *, legacy=True):
        self.rules |= {'cadence': 'batch3', 'mode': 'publish'}
        drive.write_private(self.directory / auto.SETTINGS, self.rules)
        for _ in range(3):
            self.assertEqual(auto.tick(app.connect, self.directory, self.client), 'prepared')
        with app.connect() as conn:
            rows = conn.execute('''SELECT p.id,c.theme,c.phrase_index FROM posts p
                JOIN feed_compositions c ON c.post_id=p.id ORDER BY p.id''').fetchall()
            if legacy:
                for row in rows:
                    conn.execute('UPDATE posts SET caption=? WHERE id=?',
                                 (composer.legacy_caption(row['theme'], row['phrase_index']), row['id']))
        return [row['id'] for row in rows]

    def snapshot(self):
        with app.connect() as conn:
            return {
                'posts': {row['id']: dict(row) for row in conn.execute('SELECT * FROM posts ORDER BY id')},
                'schedules': {row['post_id']: dict(row) for row in conn.execute('SELECT * FROM post_schedule ORDER BY post_id')},
                'slots': [dict(row) for row in conn.execute('SELECT * FROM feed_auto_slots ORDER BY rowid')],
                'compositions': [dict(row) for row in conn.execute('SELECT * FROM feed_compositions ORDER BY rowid')],
            }

    def restore(self, original):
        """Reset only fixture rows between protected-state examples."""
        with app.connect() as conn:
            for row in original['posts'].values():
                columns = [name for name in row if name != 'id']
                conn.execute('UPDATE posts SET '+','.join(name+'=?' for name in columns)+' WHERE id=?',
                             [row[name] for name in columns]+[row['id']])
            for row in original['schedules'].values():
                columns = [name for name in row if name != 'post_id']
                conn.execute('UPDATE post_schedule SET '+','.join(name+'=?' for name in columns)+' WHERE post_id=?',
                             [row[name] for name in columns]+[row['post_id']])

    def test_future_feeds_use_the_full_caption_independent_of_art_phrase(self):
        ids = self.queue(legacy=False)
        caption = composer.standard_caption()
        self.assertLessEqual(len(caption), 2200)
        self.assertEqual(caption.splitlines()[0], '✨ ARTE NO ALTAR | Ideias que Edificam! 🙏')
        self.assertEqual(caption.count('#'), 9)
        self.assertNotIn('**', caption)
        self.assertNotIn('](', caption)
        self.assertNotIn('35 9 8442-8442', caption)
        for text in ('100 unidades — R$ 99,00', '200 unidades — R$ 149,00',
                     '500 unidades — R$ 229,00', '1.000 unidades — R$ 399,00',
                     'www.artenoaltar.com.br', 'Instagram: @arte.no.altar',
                     '#ProjetoDeVida2027', '#PocosDeCaldas'):
            self.assertIn(text, caption)
        snapshot = self.snapshot()
        self.assertEqual([snapshot['posts'][ident]['caption'] for ident in ids], [caption]*3)
        self.assertEqual(len({row['phrase_index'] for row in snapshot['compositions']}), 3)

    def test_queued_captions_change_without_regenerating_or_rescheduling(self):
        ids = self.queue()
        before = self.snapshot()
        policy_bytes = (self.directory / auto.SETTINGS).read_bytes()
        art = {ident: (self.directory / 'media' / before['posts'][ident]['image_name']).read_bytes()
               for ident in ids}
        with patch('publishing.publish', side_effect=AssertionError('must not publish')), \
                patch('feed_composer.render', side_effect=AssertionError('must not regenerate')), \
                patch('meta.verify_accounts', side_effect=AssertionError('must not reconnect')):
            result = auto.apply_caption_standard(app.connect, self.directory)
        self.assertEqual(sorted(result['updated']), ids)
        self.assertEqual(result['skipped'], [])
        after = self.snapshot()
        for ident in ids:
            expected = before['posts'][ident] | {'caption': composer.standard_caption(), 'revision': 1}
            self.assertEqual(after['posts'][ident], expected)
            self.assertEqual(after['schedules'][ident], before['schedules'][ident] | {'revision': 1})
            self.assertEqual((self.directory / 'media' / after['posts'][ident]['image_name']).read_bytes(), art[ident])
        self.assertEqual(after['slots'], before['slots'])
        self.assertEqual(after['compositions'], before['compositions'])
        self.assertEqual((self.directory / auto.SETTINGS).read_bytes(), policy_bytes)
        self.assertEqual(auto.policy(self.directory)['id'], self.rules['id'])

    def test_applying_the_standard_twice_is_idempotent(self):
        ids = self.queue()
        auto.apply_caption_standard(app.connect, self.directory)
        before = self.snapshot()
        result = auto.apply_caption_standard(app.connect, self.directory)
        self.assertEqual(result['updated'], [])
        self.assertEqual(sorted(result['unchanged']), ids)
        self.assertEqual(self.snapshot(), before)

    def test_edited_started_published_and_draft_content_is_protected(self):
        ident = self.queue()[0]
        original = self.snapshot()
        cases = {
            'edited': ("UPDATE posts SET caption='Alteração manual',revision=1 WHERE id=?",
                       "UPDATE post_schedule SET revision=1 WHERE post_id=?"),
            'running': ("UPDATE post_schedule SET state='running' WHERE post_id=?",),
            'processing': ("UPDATE posts SET publish_status='processing',container_id='123' WHERE id=?",
                           "UPDATE post_schedule SET state='processing' WHERE post_id=?"),
            'published': ("UPDATE posts SET publish_status='published',remote_id='456' WHERE id=?",
                          "UPDATE post_schedule SET state='done' WHERE post_id=?"),
            'draft': ("UPDATE posts SET publish_status='draft' WHERE id=?",
                      "UPDATE post_schedule SET state='cancelled' WHERE post_id=?"),
            'attempted': ("UPDATE posts SET attempt_id=7 WHERE id=?",),
        }
        for name, statements in cases.items():
            with self.subTest(name=name):
                self.restore(original)
                with app.connect() as conn:
                    for statement in statements:
                        conn.execute(statement, (ident,))
                before = self.snapshot()
                result = auto.apply_caption_standard(app.connect, self.directory)
                after = self.snapshot()
                self.assertNotIn(ident, result['updated'])
                self.assertEqual(after['posts'][ident], before['posts'][ident])
                self.assertEqual(after['schedules'][ident], before['schedules'][ident])

    def test_unowned_and_wrong_policy_content_is_untouched(self):
        ids = self.queue()
        with app.connect() as conn:
            conn.execute('UPDATE feed_auto_slots SET policy=? WHERE post_id=?', ('b'*32, ids[0]))
            conn.execute("UPDATE posts SET account_id='999999' WHERE id=?", (ids[1],))
            conn.execute('DELETE FROM feed_auto_slots WHERE post_id=?', (ids[2],))
            for source in ('Manual', 'Importação MCP · revisar'):
                ident = conn.execute('''INSERT INTO posts
                    (product,channel,caption,source,account_id,publish_status)
                    VALUES('Manual','Instagram','Texto existente',?,'123456','scheduled')''', (source,)).lastrowid
                conn.execute("INSERT INTO post_schedule(post_id,revision,due_at,state) VALUES(?,0,?,'queued')",
                             (ident, self.now+3600))
        before = self.snapshot()
        result = auto.apply_caption_standard(app.connect, self.directory)
        self.assertEqual(result['updated'], [])
        self.assertEqual(self.snapshot(), before)
        drive.write_private(self.directory / auto.SETTINGS, self.rules | {'enabled': False})
        with self.assertRaises(ValueError):
            auto.apply_caption_standard(app.connect, self.directory)
        self.assertEqual(self.snapshot(), before)

    def test_conditional_queue_update_failure_rolls_back_the_whole_batch(self):
        ids = self.queue()
        before = self.snapshot()
        with app.connect() as conn:
            conn.execute(f'''CREATE TRIGGER caption_fixture_queue_conflict
                BEFORE UPDATE OF revision ON post_schedule
                WHEN OLD.post_id={ids[1]} AND NEW.revision=OLD.revision+1
                BEGIN SELECT RAISE(IGNORE); END''')
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            auto.apply_caption_standard(app.connect, self.directory)
        self.assertEqual(self.snapshot(), before)
