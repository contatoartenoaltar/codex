import os
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app
import content_schedule
import social_insights as insights


class Reader:
    def __init__(self, values=None, error=False, insights=False):
        self.values = values or {"likes": 3, "comments": 1, "reach": 20, "views": 24,
                                 "saves": 2, "shares": 1, "replies": None}
        self.error = error
        self.insights = insights
        self.calls = []

    def collect(self, remote_id, format_):
        self.calls.append((remote_id, format_))
        if self.error:
            raise ValueError("private provider error")
        return self.values


class SocialInsightsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old_db = app.DB
        app.DB = Path(self.temp.name) / "app.db"
        self.addCleanup(setattr, app, "DB", self.old_db)
        app.initialize()
        self.now = 1_800_000_000
        self.environment = patch.dict(os.environ, {
            "ARTENOALTAR_STORIES_DIR": "",
            "ARTENOALTAR_PROMOTIONAL_STORIES_DIR": "",
            "ARTENOALTAR_CAROUSELS_DIR": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def feed(self, *, age=insights.DAY + 60, remote="ig-feed-1"):
        with app.connect() as connection:
            post = connection.execute("""INSERT INTO posts
                (product,channel,caption,source,account_id,publish_status,remote_id)
                VALUES('Envelopes','Instagram','Legenda','Automático','123','published',?)""",
                (remote,)).lastrowid
            connection.execute("""INSERT INTO post_schedule(post_id,revision,due_at,state)
                VALUES(?,0,?,'done')""", (post, self.now - age))
        return post

    def test_collects_due_feed_checkpoint_and_exposes_readiness_status(self):
        post = self.feed()
        reader = Reader()
        result = insights.tick(app.connect, app.DB.parent, now=self.now, reader=reader)
        self.assertEqual(result, {"status": "collected", "format": "feed", "checkpoint": insights.DAY})
        self.assertEqual(reader.calls, [("ig-feed-1", "feed")])
        with app.connect() as connection:
            publication = connection.execute("SELECT * FROM social_publications").fetchone()
            snapshot = connection.execute("SELECT * FROM social_metric_snapshots").fetchone()
            status = insights.status(connection)
        self.assertEqual(publication["id"], f"feed:{post}")
        self.assertEqual((snapshot["reach"], snapshot["likes"], snapshot["saves"]), (20, 3, 2))
        self.assertEqual(status["formats"], {"feed": 1})
        self.assertFalse(status["ready_for_scheduling"])
        self.assertEqual(insights.tick(app.connect, app.DB.parent, now=self.now + 60, reader=reader),
                         {"status": "idle"})

    def test_discovery_fills_image_url_for_a_publication_already_known(self):
        with app.connect() as connection:
            insights._register(connection, ident="feed:known", source="feed", source_id="known",
                remote_id="known-remote", format_="feed", title="Primeiro título",
                published_at=self.now - insights.DAY, now=self.now)
            insights._register(connection, ident="feed:known", source="feed", source_id="known",
                remote_id="known-remote", format_="feed", title="Título atualizado",
                published_at=self.now - insights.DAY, now=self.now, image_url="/media/known.jpg")
            row = connection.execute(
                "SELECT title,image_url FROM social_publications WHERE id='feed:known'").fetchone()
        self.assertEqual(tuple(row), ("Título atualizado", "/media/known.jpg"))

    def test_failure_is_generic_and_retries_only_after_one_hour(self):
        self.feed(remote="ig-feed-private")
        reader = Reader(error=True)
        self.assertEqual(insights.tick(app.connect, app.DB.parent, now=self.now, reader=reader),
                         {"status": "unavailable"})
        self.assertEqual(insights.tick(app.connect, app.DB.parent, now=self.now + 59 * 60, reader=reader),
                         {"status": "idle"})
        self.assertEqual(len(reader.calls), 1)
        self.assertEqual(insights.tick(app.connect, app.DB.parent, now=self.now + 61 * 60, reader=reader),
                         {"status": "unavailable"})
        self.assertEqual(len(reader.calls), 2)
        with app.connect() as connection:
            error = connection.execute("SELECT error FROM social_publications").fetchone()[0]
        self.assertNotIn("private", error)

    def test_new_insights_permission_refreshes_recent_missing_metrics(self):
        self.feed(remote="ig-feed-refresh")
        first = Reader(values={"likes": 2, "comments": 0, "reach": None, "views": None,
                               "saves": None, "shares": None, "replies": None})
        self.assertEqual(insights.tick(app.connect, app.DB.parent, now=self.now, reader=first)["status"],
                         "collected")
        refreshed = Reader(values={"likes": 2, "comments": 0, "reach": 31, "views": 35,
                                   "saves": 1, "shares": 2, "replies": None}, insights=True)
        result = insights.tick(app.connect, app.DB.parent, now=self.now + 60, reader=refreshed)
        self.assertEqual(result["status"], "refreshed")
        with app.connect() as connection:
            sample = connection.execute(
                "SELECT reach,views,refresh_count FROM social_metric_snapshots").fetchone()
        self.assertEqual(tuple(sample), (31, 35, 1))

    def test_discovers_recent_published_story_from_isolated_queue(self):
        directory = Path(self.temp.name) / "stories"
        (directory / "media").mkdir(parents=True)
        database = directory / "story-queue.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute(f"PRAGMA application_id={content_schedule.VERSE_APPLICATION_ID}")
        connection.execute("""CREATE TABLE slots(
            id TEXT PRIMARY KEY,due_at INTEGER,remote_id TEXT,state TEXT,verse_json TEXT,filename TEXT)""")
        connection.execute("INSERT INTO slots VALUES(?,?,?,?,?,?)", (
            "a" * 32, self.now - 3 * 60 * 60, "ig-story-1", "published",
            '{"reference":"Salmos 46:1"}', "a" * 32 + ".jpg"))
        connection.commit()
        connection.close()
        with patch.dict(os.environ, {"ARTENOALTAR_STORIES_DIR": str(directory)}):
            result = insights.tick(app.connect, app.DB.parent, now=self.now, reader=Reader())
        self.assertEqual(result, {"status": "collected", "format": "story", "checkpoint": 2 * 60 * 60})
        with app.connect() as target:
            row = target.execute("SELECT title,format FROM social_publications").fetchone()
        self.assertEqual(tuple(row), ("Versículo · Salmos 46:1", "story"))

    def test_requires_ten_sampled_publications_before_scheduling_is_ready(self):
        with app.connect() as connection:
            for index in range(10):
                insights._register(connection, ident=f"feed:{index}", source="feed",
                    source_id=str(index), remote_id=f"remote-{index}", format_="feed",
                    title="Envelope", published_at=self.now - insights.DAY, now=self.now)
                connection.execute("""INSERT INTO social_metric_snapshots
                    (publication_id,checkpoint,collected_at,reach) VALUES(?,?,?,?)""",
                    (f"feed:{index}", insights.DAY, self.now, index + 1))
            status = insights.status(connection)
        self.assertFalse(status["ready_for_scheduling"])
        self.assertEqual(status["publications"], 10)
        self.assertEqual(status["decisions"]["feed"]["reason"],
                         "Aguardando resultados em pelo menos dois horários.")

    def test_selects_best_hour_only_with_enough_comparable_results(self):
        with app.connect() as connection:
            for index in range(10):
                hour = 12 if index < 5 else 18
                local_day = datetime.fromtimestamp(self.now, insights.ZONE).date() - timedelta(days=1)
                published = int(datetime.combine(local_day, datetime.min.time(), insights.ZONE)
                                .replace(hour=hour).timestamp())
                insights._register(connection, ident=f"feed:{index}", source="feed",
                    source_id=str(index), remote_id=f"choice-{index}", format_="feed",
                    title="Envelope", published_at=published, now=self.now)
                connection.execute("""INSERT INTO social_metric_snapshots
                    (publication_id,checkpoint,collected_at,reach,likes,comments)
                    VALUES(?,?,?,?,?,?)""", (f"feed:{index}", insights.DAY, self.now,
                                              10 if hour == 12 else 30, 1, 0))
            decision = insights.analyze(connection, now=self.now)["feed"]
            stored = connection.execute(
                "SELECT state,selected_hour,sample_size FROM social_schedule_decisions WHERE format='feed'").fetchone()
        self.assertEqual(decision["state"], "selected")
        self.assertEqual(decision["selected_hour"], 18)
        self.assertEqual(tuple(stored), ("selected", 18, 10))


if __name__ == "__main__":
    unittest.main()
