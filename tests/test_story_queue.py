from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from stories import preview
from stories.queue import (Store, ZONE, enable_simulation, pause, prepare_batch,
                           queue_batch, tick, configure_live, enable_live)


class Transport:
    simulation = True

    def __init__(self):
        self.creates = []
        self.publishes = []
        self.status = 'FINISHED'

    def verify_account(self, account_id):
        return {'id': account_id, 'username': 'arte.no.altar',
                'account_type': 'BUSINESS', 'stories_allowed': True}

    def create_container(self, image, **data):
        self.creates.append((image, data))
        return {'id': 'container-' + image.stem}

    def container_status(self, container):
        return self.status

    def publish(self, container):
        self.publishes.append(container)
        return {'id': 'simulated-' + container}


class LiveTransport(Transport):
    simulation = False
    requires_staging = True
    account_id = '123456'

    def __init__(self):
        super().__init__()
        self.stages = []

    def stage_image(self, image):
        self.stages.append(image)
        return {'id': '700'}


class StoryQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'stories-only'
        self.store = Store(self.directory)
        self.store.initialize()
        self.now = datetime(2026, 11, 2, 18, tzinfo=ZONE)
        self.transport = Transport()

    def prepare(self):
        return prepare_batch(self.store, now=self.now)['batch_id']

    def ready(self):
        batch = self.prepare()
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        enable_simulation(self.store, '123456', confirmed=True)
        return batch

    def live_ready(self):
        configure_live(self.store, '123456', confirmed=True)
        batch = self.prepare()
        queue_batch(self.store, batch, confirmed=True, now=self.now)
        enable_live(self.store, confirmed=True, now=self.now)
        return LiveTransport()

    def due(self, index=0):
        return datetime.fromtimestamp(self.store.agenda()[index]['due_at'], ZONE)

    def test_three_days_at_0730_without_same_day_past_schedule(self):
        self.prepare()
        rows = self.store.agenda()
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['day'] for r in rows], ['2026-11-03', '2026-11-04', '2026-11-05'])
        self.assertEqual(len({r['verse_id'] for r in rows}), 3)
        self.assertEqual({r['state'] for r in rows}, {'draft'})
        for row in rows:
            due = datetime.fromtimestamp(row['due_at'], ZONE)
            self.assertEqual((due.hour, due.minute), (7, 30))
            self.assertEqual(due.astimezone(timezone.utc).hour, 10)

    def test_repeat_and_restart_reuse_same_files_and_history(self):
        batch = self.prepare()
        before = self.store.agenda()
        restarted = Store(self.directory)
        restarted.initialize()
        result = prepare_batch(restarted, now=self.now + timedelta(days=1))
        self.assertEqual(result, {'batch_id': batch, 'created': False})
        self.assertEqual(restarted.agenda(), before)

    def test_day_before_last_creates_next_three_without_repeating_cycle(self):
        batch = self.ready()
        before = self.store.agenda()
        result = prepare_batch(self.store, now=self.due(1))
        self.assertTrue(result['created'])
        self.assertNotEqual(result['batch_id'], batch)
        self.assertFalse(prepare_batch(self.store, now=self.due(2) - timedelta(hours=1))['created'])
        rows = self.store.agenda()
        self.assertEqual(rows[:3], before)
        self.assertEqual([r['day'] for r in rows[3:]], ['2026-11-06', '2026-11-07', '2026-11-08'])
        self.assertEqual(len({r['verse_id'] for r in rows}), 6)
        self.assertEqual({r['cycle'] for r in rows}, {1})

    def test_new_cycle_starts_only_after_using_six_and_does_not_repeat_last(self):
        self.ready()
        second = prepare_batch(self.store, now=self.due(2))['batch_id']
        queue_batch(self.store, second, confirmed=True, now=self.due(2))
        prepare_batch(self.store, now=self.due(5))
        rows = self.store.agenda()
        self.assertEqual([r['cycle'] for r in rows], [1]*6+[2]*3)
        self.assertNotEqual(rows[5]['verse_id'], rows[6]['verse_id'])

    def test_parallel_preparation_creates_only_one_batch(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: prepare_batch(self.store, now=self.now), range(2)))
        self.assertEqual(len(self.store.agenda()), 3)
        self.assertEqual(len({r['batch_id'] for r in results}), 1)
        self.assertEqual(sum(r['created'] for r in results), 1)

    def test_render_failure_rolls_back_batch_history_and_new_files(self):
        real = preview.export
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise ValueError('Falha de composição simulada')
            return real(*args, **kwargs)

        with patch('stories.queue.preview.export', side_effect=fail_second):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertEqual(self.store.agenda(), [])
        self.assertEqual(list((self.directory/'media').glob('*')), [])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM batches').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM verse_history').fetchone()[0], 0)

    def test_queue_requires_confirmation_and_cannot_queue_past_dates(self):
        batch = self.prepare()
        with self.assertRaises(ValueError):
            queue_batch(self.store, batch, now=self.now)
        with self.assertRaises(ValueError):
            queue_batch(self.store, batch, confirmed=True, now=self.due())
        self.assertEqual({r['state'] for r in self.store.agenda()}, {'draft'})

    def test_altered_image_blocks_whole_batch_before_queue(self):
        batch = self.prepare()
        row = self.store.agenda()[1]
        (self.directory/'media'/row['filename']).write_bytes(b'alterada')
        with self.assertRaises(ValueError):
            queue_batch(self.store, batch, confirmed=True, now=self.now)
        self.assertEqual({r['state'] for r in self.store.agenda()}, {'draft'})

    def test_disabled_unconfigured_future_and_paused_never_send(self):
        self.assertEqual(tick(self.store, self.transport, now=self.now)['status'], 'disabled')
        self.ready()
        self.assertEqual(tick(self.store, now=self.due())['status'], 'unconfigured')
        self.assertEqual(tick(self.store, object(), now=self.due())['status'], 'unconfigured')
        self.assertEqual(tick(self.store, self.transport, now=self.now)['status'], 'idle')
        pause(self.store)
        self.assertEqual(tick(self.store, self.transport, now=self.due())['status'], 'disabled')
        self.assertEqual(self.transport.creates, [])

    def test_story_container_processing_and_exactly_one_simulated_publish(self):
        self.ready()
        due = self.due()
        self.assertEqual(tick(self.store, self.transport, now=due)['status'], 'processing')
        self.assertEqual(self.transport.creates[0][1], {'media_type': 'STORIES'})
        self.transport.status = 'IN_PROGRESS'
        self.assertEqual(tick(self.store, self.transport, now=due+timedelta(minutes=1))['status'], 'processing')
        self.transport.status = 'FINISHED'
        self.assertEqual(tick(self.store, self.transport, now=due+timedelta(minutes=2))['status'], 'simulated')
        self.assertEqual(tick(self.store, self.transport, now=due+timedelta(minutes=3))['status'], 'idle')
        self.assertEqual(len(self.transport.creates), 1)
        self.assertEqual(len(self.transport.publishes), 1)

    def test_parallel_ticks_do_not_create_duplicate_containers(self):
        self.ready()
        entered, release = threading.Event(), threading.Event()
        create = self.transport.create_container

        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError('Teste concorrente não liberou o envio')
            return create(*args, **kwargs)

        with patch.object(self.transport, 'create_container', side_effect=blocked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(tick, self.store, self.transport, now=self.due())
                self.assertTrue(entered.wait(10))
                try:
                    self.assertEqual(tick(self.store, self.transport, now=self.due())['status'], 'busy')
                finally:
                    release.set()
                self.assertEqual(first.result()['status'], 'processing')
        self.assertEqual(len(self.transport.creates), 1)

    def test_late_and_uncertain_results_require_review_without_retry(self):
        self.ready()
        self.assertEqual(tick(self.store, self.transport, now=self.due()+timedelta(minutes=31))['status'], 'expired')
        self.assertEqual(self.transport.creates, [])
        due = self.due(1)
        tick(self.store, self.transport, now=due)
        with patch.object(self.transport, 'publish', side_effect=TimeoutError('segredo não deve aparecer')):
            self.assertEqual(tick(self.store, self.transport, now=due+timedelta(minutes=1))['status'], 'review')
        self.assertEqual(tick(self.store, self.transport, now=due+timedelta(minutes=2))['status'],
                         'batch_prepared')
        self.assertNotIn('segredo', str(self.store.agenda()))
        self.assertEqual(self.transport.publishes, [])

    def test_wrong_account_or_edited_art_is_not_sent(self):
        self.ready()
        with patch.object(self.transport, 'verify_account', return_value={'id': 'other'}):
            self.assertEqual(tick(self.store, self.transport, now=self.due())['status'], 'review')
        row = self.store.agenda()[1]
        (self.directory/'media'/row['filename']).write_bytes(b'alterada')
        self.assertEqual(tick(self.store, self.transport, now=self.due(1))['status'], 'review')
        self.assertEqual(self.transport.creates, [])

    def test_abandoned_claim_is_not_retried(self):
        self.ready()
        due = self.due()
        with self.store.connect() as conn:
            conn.execute("UPDATE slots SET state='sending',claimed_at=? WHERE id=?", (int(due.timestamp()), self.store.agenda()[0]['id']))
        self.assertEqual(tick(self.store, self.transport, now=due+timedelta(minutes=11))['status'], 'idle')
        self.assertEqual(self.store.agenda()[0]['state'], 'review')
        self.assertEqual(self.transport.creates, [])

    def test_idle_third_day_tick_prepares_and_queues_exactly_next_batch(self):
        self.ready()
        now = self.due(2)-timedelta(hours=2)
        self.assertEqual(tick(self.store, self.transport, now=now)['status'], 'expired')
        self.assertEqual(tick(self.store, self.transport, now=now)['status'], 'expired')
        self.assertEqual(tick(self.store, self.transport, now=now)['status'], 'batch_prepared')
        self.assertEqual(len(self.store.agenda()), 6)
        self.assertEqual({r['state'] for r in self.store.agenda()[3:]}, {'queued'})
        self.assertEqual(tick(self.store, self.transport, now=now)['status'], 'idle')

    def test_foreign_database_and_symlinks_are_refused_without_changes(self):
        other = Store(Path(self.temp.name)/'foreign')
        other.directory.mkdir()
        with sqlite3.connect(other.path) as conn:
            conn.execute('CREATE TABLE transactions(id INTEGER PRIMARY KEY, amount INTEGER)')
            conn.execute('INSERT INTO transactions VALUES(1,12345)')
        before = hashlib.sha256(other.path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            other.initialize()
        self.assertEqual(hashlib.sha256(other.path.read_bytes()).hexdigest(), before)
        link = Path(self.temp.name)/'link'
        link.symlink_to(self.directory)
        with self.assertRaises(ValueError):
            Store(link)

    def test_naive_clock_is_refused_and_early_morning_can_include_today(self):
        with self.assertRaises(ValueError):
            prepare_batch(self.store, now=datetime(2026, 11, 2, 6))
        prepare_batch(self.store, now=datetime(2026, 11, 2, 6, tzinfo=ZONE))
        self.assertEqual(self.store.agenda()[0]['day'], '2026-11-02')

    def test_approval_change_and_other_account_cannot_be_silently_accepted(self):
        self.ready()
        with self.assertRaises(ValueError):
            enable_simulation(self.store, '999999', confirmed=True)
        with patch('stories.preview.APPROVAL', Path(self.temp.name)/'missing.json'):
            with self.assertRaises(ValueError):
                prepare_batch(self.store, now=self.due(2))
            self.assertEqual(tick(self.store, self.transport, now=self.due())['status'], 'review')
        self.assertEqual(self.transport.creates, [])

    def test_media_symlink_is_refused_before_creating_files_elsewhere(self):
        external = Path(self.temp.name)/'external'
        external.mkdir()
        (self.directory/'media').symlink_to(external)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual(self.store.agenda(), [])

    def test_live_mode_requires_fresh_store_and_separate_activation(self):
        with self.assertRaises(ValueError):
            configure_live(self.store, '123456')
        configure_live(self.store, '123456', confirmed=True)
        self.assertEqual(tick(self.store, LiveTransport(), now=self.now)['status'], 'disabled')
        with self.assertRaises(ValueError):
            enable_live(self.store, confirmed=True, now=self.now)
        with self.assertRaises(ValueError):
            enable_simulation(self.store, '123456', confirmed=True)
        self.prepare()
        with self.assertRaises(ValueError):
            configure_live(self.store, '123456', confirmed=True)

    def test_simulated_queue_cannot_be_promoted_and_modes_cannot_cross(self):
        self.ready()
        with self.assertRaises(ValueError):
            configure_live(self.store, '123456', confirmed=True)
        self.assertEqual(tick(self.store, LiveTransport(), now=self.due())['status'], 'unconfigured')
        self.assertEqual({r['state'] for r in self.store.agenda()}, {'queued'})

    def test_live_pipeline_persists_photo_then_container_then_publication(self):
        transport = self.live_ready()
        due = self.due()
        self.assertEqual(tick(self.store, self.transport, now=due)['status'], 'unconfigured')
        self.assertEqual(tick(self.store, transport, now=due)['status'], 'staged')
        self.assertEqual(self.store.agenda()[0]['staged_photo'], '700')
        self.assertEqual(transport.creates, [])
        self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=1))['status'], 'processing')
        self.assertEqual(transport.creates[0][1], {'media_type': 'STORIES', 'staged_photo': '700'})
        self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=2))['status'], 'published')
        self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=3))['status'], 'idle')
        self.assertEqual(len(transport.stages), 1)
        self.assertEqual(len(transport.creates), 1)
        self.assertEqual(len(transport.publishes), 1)

    def test_lost_staging_response_retries_twice_then_requires_review(self):
        transport = self.live_ready()
        with patch.object(transport, 'stage_image', side_effect=TimeoutError('synthetic-secret')) as stage:
            self.assertEqual(tick(self.store, transport, now=self.due())['status'], 'queued')
            self.assertEqual(tick(self.store, transport, now=self.due()+timedelta(minutes=1))['status'], 'queued')
            self.assertEqual(tick(self.store, transport, now=self.due()+timedelta(minutes=2))['status'], 'review')
            self.assertEqual(tick(self.store, transport, now=self.due()+timedelta(minutes=3))['status'], 'idle')
        self.assertEqual(stage.call_count, 3)
        with self.store.connect() as conn:
            self.assertEqual([r[0] for r in conn.execute('SELECT outcome FROM attempts ORDER BY created_at')],
                             ['retry', 'retry', 'review'])
        self.assertNotIn('synthetic-secret', str(self.store.agenda()))

    def test_transient_container_failure_recovers_without_duplicate_publication(self):
        transport = self.live_ready()
        due = self.due()
        self.assertEqual(tick(self.store, transport, now=due)['status'], 'staged')
        original = transport.create_container
        calls = 0

        def transient(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError('temporary-container-error')
            return original(*args, **kwargs)

        with patch.object(transport, 'create_container', side_effect=transient):
            self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=1))['status'], 'staged')
            row = self.store.agenda()[0]
            self.assertIn('nova tentativa 2 de 3', row['error'])
            self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=2))['status'], 'processing')
        self.assertEqual(self.store.agenda()[0]['error'], '')
        self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=3))['status'], 'published')
        self.assertEqual(len(transport.publishes), 1)

    def test_uncertain_publish_is_never_retried(self):
        transport = self.live_ready()
        due = self.due()
        self.assertEqual(tick(self.store, transport, now=due)['status'], 'staged')
        self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=1))['status'], 'processing')
        with patch.object(transport, 'publish', side_effect=TimeoutError('uncertain-publish')) as publish:
            self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=2))['status'], 'review')
            self.assertEqual(tick(self.store, transport, now=due+timedelta(minutes=3))['status'], 'idle')
        self.assertEqual(publish.call_count, 1)

    def test_interrupted_process_after_upload_requires_review_without_repeating(self):
        transport = self.live_ready()
        with patch.object(transport, 'stage_image', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                tick(self.store, transport, now=self.due())
        self.assertEqual(self.store.agenda()[0]['state'], 'sending')
        tick(self.store, transport, now=self.due()+timedelta(minutes=11))
        self.assertEqual(self.store.agenda()[0]['state'], 'review')
        self.assertEqual(transport.stages, [])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT outcome FROM attempts').fetchone()[0], 'review')

    def test_live_account_mismatch_and_missing_confirmation_do_not_send(self):
        transport = self.live_ready()
        transport.account_id = '999999'
        self.assertEqual(tick(self.store, transport, now=self.due())['status'], 'unconfigured')
        pause(self.store)
        with self.assertRaises(ValueError):
            enable_live(self.store, now=self.now)
        self.assertEqual(tick(self.store, transport, now=self.due())['status'], 'disabled')

    def test_claim_lost_after_remote_write_does_not_override_review(self):
        transport = self.live_ready()
        original = transport.stage_image

        def revoked(image):
            result = original(image)
            with self.store.connect() as conn:
                conn.execute("UPDATE slots SET state='review' WHERE state='sending'")
            return result

        with patch.object(transport, 'stage_image', side_effect=revoked):
            self.assertEqual(tick(self.store, transport, now=self.due())['status'], 'review')
        self.assertEqual(self.store.agenda()[0]['state'], 'review')
        self.assertEqual(transport.creates, [])

    def test_live_preparation_can_start_early_but_publish_waits_for_authorized_time(self):
        transport = self.live_ready()
        due = self.due()
        self.assertEqual(tick(self.store, transport, now=due-timedelta(minutes=6))['status'], 'idle')
        self.assertEqual(tick(self.store, transport, now=due-timedelta(minutes=5))['status'], 'staged')
        self.assertEqual(tick(self.store, transport, now=due-timedelta(minutes=4))['status'], 'processing')
        self.assertEqual(tick(self.store, transport, now=due-timedelta(seconds=1))['status'], 'idle')
        self.assertEqual(transport.publishes, [])
        self.assertEqual(tick(self.store, transport, now=due)['status'], 'published')
        self.assertEqual(len(transport.publishes), 1)

    def test_own_previous_schema_upgrades_without_erasing_slots_or_enabling_live(self):
        from stories.queue import SCHEMA, APPLICATION_ID
        old = Store(Path(self.temp.name)/'older-stories')
        old.directory.mkdir()
        with sqlite3.connect(old.path) as conn:
            conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
            for statement in SCHEMA:
                conn.execute(statement)
            conn.execute("INSERT INTO policy VALUES(1,0,'simulation','')")
            conn.execute("INSERT INTO batches VALUES('old-batch','2026-11-03','2026-11-05',1)")
            conn.execute("""INSERT INTO slots(id,batch_id,day,due_at,verse_id,verse_json,cycle,
                filename,image_hash,manifest_hash,state) VALUES(
                'old-slot','old-batch','2026-11-03',1,'php-4-13','{}',1,'original.jpg','hash','manifest','draft')""")
            before = conn.execute('SELECT * FROM slots').fetchone()
        old.initialize()
        old.initialize()
        with old.connect() as conn:
            after = conn.execute('SELECT * FROM slots').fetchone()
            self.assertEqual(tuple(after)[:-1], before)
            self.assertEqual(after['staged_photo'], '')
            self.assertEqual(tuple(conn.execute('SELECT * FROM policy').fetchone()), (1, 0, 'simulation', ''))
