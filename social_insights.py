"""Coleta enxuta de resultados orgânicos para orientar horários futuros."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import content_schedule
import meta
import social_schedule


DAY = 24 * 60 * 60
WINDOWS = {
    "feed": (DAY, 7 * DAY),
    "carousel": (DAY, 7 * DAY),
    "story": (2 * 60 * 60, 12 * 60 * 60, 23 * 60 * 60),
}
ANALYSIS_CHECKPOINT = {"feed": DAY, "carousel": DAY, "story": 12 * 60 * 60}
MIN_COMPARABLE = 10
ZONE = ZoneInfo("America/Sao_Paulo")


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS social_publications (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_id TEXT NOT NULL,
        remote_id TEXT NOT NULL UNIQUE,
        format TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at INTEGER NOT NULL,
        discovered_at INTEGER NOT NULL,
        last_collected_at INTEGER,
        collection_state TEXT NOT NULL DEFAULT 'pending',
        error TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS social_metric_snapshots (
        publication_id TEXT NOT NULL REFERENCES social_publications(id),
        checkpoint INTEGER NOT NULL,
        collected_at INTEGER NOT NULL,
        likes INTEGER,
        comments INTEGER,
        reach INTEGER,
        views INTEGER,
        saves INTEGER,
        shares INTEGER,
        replies INTEGER,
        refresh_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(publication_id, checkpoint)
    );
    CREATE INDEX IF NOT EXISTS social_publications_due
        ON social_publications(collection_state, published_at);
    CREATE TABLE IF NOT EXISTS social_schedule_decisions (
        format TEXT PRIMARY KEY,
        state TEXT NOT NULL,
        selected_hour INTEGER,
        sample_size INTEGER NOT NULL,
        alternatives INTEGER NOT NULL,
        decided_at INTEGER NOT NULL,
        reason TEXT NOT NULL
    );
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(social_publications)")}
    if "image_url" not in columns:
        conn.execute("ALTER TABLE social_publications ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
    metric_columns = {row[1] for row in conn.execute("PRAGMA table_info(social_metric_snapshots)")}
    if "refresh_count" not in metric_columns:
        conn.execute("ALTER TABLE social_metric_snapshots ADD COLUMN refresh_count INTEGER NOT NULL DEFAULT 0")


def _safe_title(value, fallback):
    return value.strip()[:160] if isinstance(value, str) and value.strip() else fallback


def _register(conn, *, ident, source, source_id, remote_id, format_, title, published_at, now,
              image_url=""):
    if (not isinstance(remote_id, str) or not remote_id or
            format_ not in WINDOWS or type(published_at) is not int):
        return
    conn.execute("""INSERT INTO social_publications
        (id,source,source_id,remote_id,format,title,published_at,discovered_at,image_url)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            image_url=CASE WHEN excluded.image_url!='' THEN excluded.image_url
                           ELSE social_publications.image_url END""",
        (ident, source, source_id, remote_id, format_, _safe_title(title, format_.title()),
         published_at, now, image_url if isinstance(image_url, str) else ""))


def discover(connect, *, now=None):
    """Registra publicações recentes sem copiar artes, legendas ou dados pessoais."""
    now = int(time.time() if now is None else now)
    oldest = now - 28 * DAY
    with connect() as conn:
        initialize(conn)
        rows = conn.execute("""SELECT p.id,p.product,p.channel,p.remote_id,p.image_name,s.due_at
            FROM posts p JOIN post_schedule s ON s.post_id=p.id
            WHERE p.publish_status='published' AND p.remote_id!='' AND p.channel LIKE 'Instagram%'
              AND s.due_at>=?""",
            (oldest,)).fetchall()
        for row in rows:
            _register(conn, ident=f"feed:{row['id']}", source="feed", source_id=str(row["id"]),
                      remote_id=row["remote_id"], format_="feed", title=row["product"],
                      published_at=row["due_at"], now=now,
                      image_url=f"/media/{row['image_name']}" if row["image_name"] else "")

    for kind in ("verse", "promotional", "carousel"):
        try:
            _, _, media, connection = content_schedule._connect(kind)
            try:
                if kind == "carousel":
                    rows = connection.execute("""SELECT id,faq_id,due_at,remote_id
                        FROM carousels WHERE state='published' AND remote_id!='' AND due_at>=?""",
                        (oldest,)).fetchall()
                else:
                    columns = "id,due_at,remote_id,verse_json,filename" if kind == "verse" else \
                              "id,due_at,remote_id,model_name,filename"
                    rows = connection.execute(
                        f"SELECT {columns} FROM slots WHERE state='published' "
                        "AND remote_id!='' AND due_at>=?", (now - DAY,)).fetchall()
                with connect() as target:
                    initialize(target)
                    for row in rows:
                        if kind == "verse":
                            try:
                                title = "Versículo · " + json.loads(row["verse_json"])["reference"]
                            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                                title = "Versículo diário"
                        elif kind == "promotional":
                            title = row["model_name"]
                        else:
                            title = row["faq_id"]
                        _register(target, ident=f"{kind}:{row['id']}", source=kind,
                                  source_id=row["id"], remote_id=row["remote_id"],
                                  format_="carousel" if kind == "carousel" else "story",
                                  title=title, published_at=row["due_at"], now=now,
                                  image_url=(f"/api/content-media/carousel/{row['id']}-01.jpg"
                                             if kind == "carousel" else
                                             f"/api/content-media/{kind}/{row['filename']}"))
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            continue


def _metric_value(payload, name):
    for item in payload.get("data", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict) or item.get("name") != name:
            continue
        value = item.get("total_value", {}).get("value") if isinstance(item.get("total_value"), dict) else None
        if value is None:
            values = item.get("values")
            value = values[-1].get("value") if isinstance(values, list) and values and isinstance(values[-1], dict) else None
        if type(value) in (int, float) and value >= 0:
            return int(value)
    return None


class MetaReader:
    """Adaptador pequeno e substituível nos testes; nunca expõe token ou respostas brutas."""
    def __init__(self, directory):
        self.settings = meta.config(directory)
        stored = meta.read_private(directory / "meta-connection.json")
        self.token = stored.get("access_token", "")
        if not self.token or stored.get("app_id") != self.settings["app_id"]:
            raise ValueError("Conecte novamente a Meta para coletar os resultados.")
        self.proof = hmac.new(self.settings["app_secret"].encode(), self.token.encode(), hashlib.sha256).hexdigest()
        verification = meta.read_private(directory / "meta-verification.json")
        self.insights = "instagram_manage_insights" in verification.get("permissions", [])

    def collect(self, remote_id, format_):
        base = meta.graph_read(self.settings, remote_id, self.token, {
            "fields": "id,like_count,comments_count", "appsecret_proof": self.proof})
        result = {
            "likes": base.get("like_count") if type(base.get("like_count")) is int else None,
            "comments": base.get("comments_count") if type(base.get("comments_count")) is int else None,
            "reach": None, "views": None, "saves": None, "shares": None, "replies": None,
        }
        if not self.insights:
            return result
        names = ("reach", "views", "saved", "shares")
        if format_ == "story":
            names = ("reach", "views", "shares", "replies")
        for name in names:
            try:
                payload = meta.graph_read(self.settings, remote_id + "/insights", self.token, {
                    "metric": name, "appsecret_proof": self.proof})
                target = "saves" if name == "saved" else name
                result[target] = _metric_value(payload, name)
            except ValueError:
                # Métricas variam por formato, versão e permissão. Ausente não significa zero.
                continue
        return result


def _next_due(conn, now, *, refresh_missing=False):
    rows = conn.execute("""SELECT * FROM social_publications
        WHERE collection_state IN ('pending','collecting','complete') ORDER BY published_at""").fetchall()
    for row in rows:
        if row["error"] and row["last_collected_at"] and row["last_collected_at"] > now - 60 * 60:
            continue
        samples = {item["checkpoint"]: item for item in conn.execute(
            "SELECT * FROM social_metric_snapshots WHERE publication_id=?", (row["id"],))}
        if refresh_missing and not (row["format"] == "story" and now - row["published_at"] > DAY):
            for checkpoint in WINDOWS[row["format"]]:
                sample = samples.get(checkpoint)
                if (sample and sample["reach"] is None and sample["views"] is None and
                        sample["refresh_count"] < 3 and
                        (sample["refresh_count"] == 0 or sample["collected_at"] <= now - 60 * 60)):
                    return dict(row), checkpoint, True
        sampled = set(samples)
        remaining = [value for value in WINDOWS[row["format"]] if value not in sampled]
        if not remaining:
            conn.execute("UPDATE social_publications SET collection_state='complete' WHERE id=?", (row["id"],))
            continue
        due = row["published_at"] + remaining[0]
        if due <= now:
            return dict(row), remaining[0], False
    return None, None, False


def tick(connect, directory, *, now=None, reader=None):
    """Descobre tudo e coleta no máximo um checkpoint por chamada do cron."""
    now = int(time.time() if now is None else now)
    discover(connect, now=now)
    verification = meta.read_private(directory / "meta-verification.json")
    refresh_missing = "instagram_manage_insights" in verification.get("permissions", [])
    if reader is not None and hasattr(reader, "insights"):
        refresh_missing = bool(reader.insights)
    with connect() as conn:
        initialize(conn)
        publication, checkpoint, refreshing = _next_due(conn, now, refresh_missing=refresh_missing)
    if publication is None:
        with connect() as conn:
            decisions = analyze(conn, now=now)
        social_schedule.save(directory, decisions, generated_at=now)
        return {"status": "idle"}
    try:
        values = (reader or MetaReader(directory)).collect(publication["remote_id"], publication["format"])
        with connect() as conn:
            columns = (publication["id"], checkpoint, now, values.get("likes"), values.get("comments"),
                       values.get("reach"), values.get("views"), values.get("saves"),
                       values.get("shares"), values.get("replies"), 0)
            conn.execute("""INSERT INTO social_metric_snapshots
                (publication_id,checkpoint,collected_at,likes,comments,reach,views,saves,shares,replies,refresh_count)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(publication_id,checkpoint) DO UPDATE SET
                    collected_at=excluded.collected_at,likes=excluded.likes,comments=excluded.comments,
                    reach=excluded.reach,views=excluded.views,saves=excluded.saves,
                    shares=excluded.shares,replies=excluded.replies,
                    refresh_count=social_metric_snapshots.refresh_count+1""", columns)
            conn.execute("""UPDATE social_publications SET last_collected_at=?,collection_state='collecting',error=''
                WHERE id=?""", (now, publication["id"]))
            _next_due(conn, now)
            decisions = analyze(conn, now=now)
        social_schedule.save(directory, decisions, generated_at=now)
        return {"status": "refreshed" if refreshing else "collected",
                "format": publication["format"], "checkpoint": checkpoint}
    except (OSError, ValueError, sqlite3.Error):
        with connect() as conn:
            conn.execute("""UPDATE social_publications SET last_collected_at=?,error=?,collection_state='pending'
                WHERE id=?""", (now, "A coleta da Meta não ficou disponível nesta tentativa.",
                                 publication["id"]))
        return {"status": "unavailable"}


def _score(row):
    distribution = row["reach"] if row["reach"] is not None else row["views"]
    distribution = distribution or 0
    interactions = sum(row[name] or 0 for name in ("likes", "comments", "saves", "shares", "replies"))
    return distribution + interactions


def analyze(conn, *, now=None):
    """Escolhe horários somente quando há amostra e alternativas comparáveis."""
    now = int(time.time() if now is None else now)
    rows = conn.execute("""SELECT p.id,p.source,p.format,p.published_at,s.*
        FROM social_publications p JOIN social_metric_snapshots s ON s.publication_id=p.id
        WHERE s.checkpoint=CASE p.format
            WHEN 'feed' THEN 86400 WHEN 'carousel' THEN 86400 ELSE 43200 END""").fetchall()
    decisions = {}
    for format_ in WINDOWS:
        # O versículo diário é editorial e tem horário fixo (07:30). Seus
        # resultados continuam visíveis no Estúdio, mas não devem orientar
        # a decisão automática de horário dos Stories promocionais.
        values = [row for row in rows if row["format"] == format_ and
                  not (format_ == "story" and row["source"] == "verse")]
        by_hour = {}
        for row in values:
            hour = datetime.fromtimestamp(row["published_at"], ZONE).hour
            by_hour.setdefault(hour, []).append(_score(row))
        eligible = {hour: scores for hour, scores in by_hour.items() if len(scores) >= 2}
        if len(values) < MIN_COMPARABLE:
            state, selected, reason = "learning", None, "Aguardando 10 publicações comparáveis."
        elif len(eligible) < 2:
            state, selected, reason = "learning", None, "Aguardando resultados em pelo menos dois horários."
        else:
            averages = {hour: sum(scores) / len(scores) for hour, scores in eligible.items()}
            ordered = sorted(averages, key=lambda hour: (-averages[hour], hour))
            if averages[ordered[0]] == averages[ordered[1]]:
                state, selected, reason = "learning", None, "Os melhores horários ainda estão empatados."
            else:
                state, selected = "selected", ordered[0]
                reason = f"Melhor média observada entre {len(eligible)} horários comparáveis."
        conn.execute("""INSERT OR REPLACE INTO social_schedule_decisions
            (format,state,selected_hour,sample_size,alternatives,decided_at,reason)
            VALUES(?,?,?,?,?,?,?)""",
            (format_, state, selected, len(values), len(eligible), now, reason))
        decisions[format_] = {"state": state, "selected_hour": selected,
                              "sample_size": len(values), "alternatives": len(eligible),
                              "reason": reason}
    return decisions


def status(conn):
    initialize(conn)
    publications = conn.execute("SELECT COUNT(*) FROM social_publications").fetchone()[0]
    snapshots = conn.execute("SELECT COUNT(*) FROM social_metric_snapshots").fetchone()[0]
    comparable = conn.execute("""SELECT COUNT(*) FROM social_publications p
        WHERE EXISTS (SELECT 1 FROM social_metric_snapshots s WHERE s.publication_id=p.id)""").fetchone()[0]
    formats = {row[0]: row[1] for row in conn.execute(
        "SELECT format,COUNT(*) FROM social_publications GROUP BY format")}
    decisions = analyze(conn)
    latest = conn.execute("""SELECT p.id,p.source,p.format,p.title,p.published_at,p.image_url,
        s.checkpoint,s.collected_at,s.likes,s.comments,s.reach,s.views,s.saves,s.shares,s.replies
        FROM social_publications p JOIN social_metric_snapshots s ON s.publication_id=p.id
        WHERE s.checkpoint=(SELECT MAX(last.checkpoint) FROM social_metric_snapshots last
                            WHERE last.publication_id=p.id)
        ORDER BY p.published_at DESC LIMIT 120""").fetchall()
    measured = [dict(row) for row in latest]
    return {"publications": publications, "snapshots": snapshots, "formats": formats,
            "minimum_comparable": MIN_COMPARABLE,
            "ready_for_scheduling": any(item["state"] == "selected" for item in decisions.values()),
            "decisions": decisions, "measured_publications": measured,
            "last_collected_at": max((row["collected_at"] for row in latest), default=None)}
