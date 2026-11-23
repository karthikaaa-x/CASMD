"""
SQLite storage layer.

Collectors WRITE posts/accounts here; analysis READS them and WRITES its derived
records back (relevance, media clusters, narratives, coordination groups,
propagation edges, timeline). Keeping collection and analysis decoupled is
deliberate: collection is slow, rate-limited and flaky, while analysis gets
re-run many times as thresholds are tuned. Collect once, analyze many.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .schema import Post, Account, Media, iso_to_dt


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id          TEXT PRIMARY KEY,
    platform            TEXT NOT NULL,
    handle              TEXT,
    display_name        TEXT,
    kind                TEXT,
    description         TEXT,
    created_at          TEXT,
    profile_photo_phash TEXT,
    profile_photo_url   TEXT,
    external_links      TEXT,
    followers           INTEGER DEFAULT 0,
    raw                 TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    post_id            TEXT PRIMARY KEY,
    platform           TEXT NOT NULL,
    account_id         TEXT NOT NULL,
    timestamp          TEXT NOT NULL,
    kind               TEXT,
    text               TEXT,
    lang               TEXT,
    media              TEXT,
    likes              INTEGER DEFAULT 0,
    shares             INTEGER DEFAULT 0,
    replies            INTEGER DEFAULT 0,
    views              INTEGER DEFAULT 0,
    url                TEXT,
    reply_to           TEXT,
    forward_from       TEXT,
    quote_of           TEXT,
    parent_id          TEXT,
    relevance_score    REAL DEFAULT 0,
    relevance_decision TEXT DEFAULT 'unscored',
    relevance_reason   TEXT,
    relevance_signals  TEXT,
    is_generic         INTEGER DEFAULT 0,
    raw                TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_ts       ON posts(timestamp);
CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform);
CREATE INDEX IF NOT EXISTS idx_posts_account  ON posts(account_id);

-- Analysis output tables -------------------------------------------------- --
CREATE TABLE IF NOT EXISTS incident (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS media_clusters (
    cluster_id    INTEGER PRIMARY KEY,
    sha256        TEXT,
    phash         TEXT,
    confidence    TEXT,
    match_types   TEXT,     -- JSON list
    asset_ids     TEXT,     -- JSON list
    post_ids      TEXT,     -- JSON list
    account_ids   TEXT,     -- JSON list
    platforms     TEXT,     -- JSON list
    first_observed TEXT,
    evidence      TEXT
);

CREATE TABLE IF NOT EXISTS narratives (
    narrative_id INTEGER PRIMARY KEY,
    label        TEXT,
    stance       TEXT,
    keywords     TEXT,
    size         INTEGER
);

CREATE TABLE IF NOT EXISTS post_narrative (
    post_id      TEXT,
    narrative_id INTEGER
);

CREATE TABLE IF NOT EXISTS coord_groups (
    group_id        INTEGER PRIMARY KEY,
    classification  TEXT,
    confidence      TEXT,
    account_ids     TEXT,       -- JSON list
    score           REAL,
    detectors       TEXT,       -- JSON list of detector names that fired
    evidence        TEXT        -- human-readable evidence string
);

CREATE TABLE IF NOT EXISTS propagation_edges (
    src       TEXT,
    dst       TEXT,
    edge_type TEXT,
    ts_src    TEXT,
    ts_dst    TEXT,
    evidence  TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # -- writing (collectors) --------------------------------------------- #
    def upsert_account(self, acc: Account) -> None:
        r = acc.to_row()
        self.conn.execute(
            """INSERT INTO accounts
               (account_id, platform, handle, display_name, kind, description,
                created_at, profile_photo_phash, profile_photo_url,
                external_links, followers, raw)
               VALUES (:account_id,:platform,:handle,:display_name,:kind,
                       :description,:created_at,:profile_photo_phash,
                       :profile_photo_url,:external_links,:followers,:raw)
               ON CONFLICT(account_id) DO UPDATE SET
                 handle=excluded.handle,
                 display_name=excluded.display_name,
                 kind=COALESCE(excluded.kind, accounts.kind),
                 description=COALESCE(excluded.description, accounts.description),
                 created_at=COALESCE(excluded.created_at, accounts.created_at),
                 profile_photo_phash=COALESCE(excluded.profile_photo_phash,
                                              accounts.profile_photo_phash),
                 profile_photo_url=COALESCE(excluded.profile_photo_url,
                                            accounts.profile_photo_url),
                 external_links=excluded.external_links,
                 followers=excluded.followers""",
            r,
        )

    def upsert_post(self, post: Post) -> None:
        r = post.to_row()
        self.conn.execute(
            """INSERT INTO posts
               (post_id, platform, account_id, timestamp, kind, text, lang,
                media, likes, shares, replies, views, url, reply_to,
                forward_from, quote_of, parent_id, relevance_score,
                relevance_decision, relevance_reason, relevance_signals,
                is_generic, raw)
               VALUES (:post_id,:platform,:account_id,:timestamp,:kind,:text,
                       :lang,:media,:likes,:shares,:replies,:views,:url,
                       :reply_to,:forward_from,:quote_of,:parent_id,
                       :relevance_score,:relevance_decision,:relevance_reason,
                       :relevance_signals,:is_generic,:raw)
               ON CONFLICT(post_id) DO UPDATE SET
                 likes=excluded.likes, shares=excluded.shares,
                 replies=excluded.replies, views=excluded.views,
                 text=excluded.text, media=excluded.media""",
            r,
        )

    def update_account_meta(self, account_id, created_at=None, phash=None,
                            description=None, external_links=None,
                            profile_photo_url=None):
        """Update only enrichment fields without touching other data."""
        from .schema import _dt_to_iso
        created = _dt_to_iso(created_at) if hasattr(created_at, "tzinfo") else created_at
        links = json.dumps(external_links) if external_links is not None else None
        self.conn.execute(
            """UPDATE accounts SET
                 created_at = COALESCE(?, created_at),
                 profile_photo_phash = COALESCE(?, profile_photo_phash),
                 description = COALESCE(?, description),
                 external_links = COALESCE(?, external_links),
                 profile_photo_url = COALESCE(?, profile_photo_url)
               WHERE account_id = ?""",
            (created, phash, description, links, profile_photo_url, account_id))

    def update_post_relevance(self, post: Post) -> None:
        self.conn.execute(
            """UPDATE posts SET
                 relevance_score=?, relevance_decision=?, relevance_reason=?,
                 relevance_signals=?, is_generic=?, media=?
               WHERE post_id=?""",
            (post.relevance_score, post.relevance_decision, post.relevance_reason,
             json.dumps(post.relevance_signals, default=str),
             1 if post.is_generic else 0,
             json.dumps([m.to_dict() for m in post.media], default=str),
             post.post_id))

    def reset(self) -> None:
        """Wipe all rows for a fresh run, without deleting the file (deleting an
        open SQLite file fails on Windows with a lock error)."""
        for t in ("posts", "accounts", "narratives", "post_narrative",
                  "coord_groups", "media_clusters", "propagation_edges",
                  "incident"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    # -- reading (analysis) ----------------------------------------------- #
    def posts(self, platform: Optional[str] = None) -> list[Post]:
        if platform:
            cur = self.conn.execute(
                "SELECT * FROM posts WHERE platform=? ORDER BY timestamp", (platform,))
        else:
            cur = self.conn.execute("SELECT * FROM posts ORDER BY timestamp")
        return [_row_to_post(row) for row in cur.fetchall()]

    def accounts(self) -> dict[str, Account]:
        cur = self.conn.execute("SELECT * FROM accounts")
        return {row["account_id"]: _row_to_account(row) for row in cur.fetchall()}

    # -- writing analysis results ----------------------------------------- #
    def save_incident(self, incident) -> None:
        self.conn.execute("DELETE FROM incident")
        rows = {
            "name": incident.name,
            "primary_keyword": incident.primary_keyword,
            "additional_keywords": json.dumps(incident.additional_keywords),
            "description": incident.description,
            "date_start": incident.date_start,
            "date_end": incident.date_end,
            "platforms": json.dumps(list(incident.platforms)),
        }
        self.conn.executemany("INSERT INTO incident VALUES (?,?)",
                              [(k, v) for k, v in rows.items()])
        self.conn.commit()

    def save_media_clusters(self, clusters) -> None:
        self.conn.execute("DELETE FROM media_clusters")
        for c in clusters:
            self.conn.execute(
                "INSERT INTO media_clusters VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (c.cluster_id, c.sha256, c.phash, c.confidence,
                 json.dumps(c.match_types), json.dumps(c.asset_ids),
                 json.dumps(c.post_ids), json.dumps(c.account_ids),
                 json.dumps(c.platforms),
                 c.first_observed.isoformat() if c.first_observed else None,
                 c.evidence))
        self.conn.commit()

    def save_narratives(self, narratives, assignments) -> None:
        self.conn.execute("DELETE FROM narratives")
        self.conn.execute("DELETE FROM post_narrative")
        for n in narratives:
            self.conn.execute(
                "INSERT INTO narratives VALUES (?,?,?,?,?)",
                (n["narrative_id"], n["label"], n.get("stance", ""),
                 json.dumps(n["keywords"]), n["size"]))
        self.conn.executemany(
            "INSERT INTO post_narrative VALUES (?,?)",
            [(pid, nid) for pid, nid in assignments])
        self.conn.commit()

    def save_coord_groups(self, groups) -> None:
        self.conn.execute("DELETE FROM coord_groups")
        for g in groups:
            self.conn.execute(
                "INSERT INTO coord_groups VALUES (?,?,?,?,?,?,?)",
                (g["group_id"], g["classification"], g["confidence"],
                 json.dumps(g["account_ids"]), g["score"],
                 json.dumps(g["detectors"]), g["evidence"]))
        self.conn.commit()

    def save_propagation(self, edges) -> None:
        self.conn.execute("DELETE FROM propagation_edges")
        for e in edges:
            self.conn.execute(
                "INSERT INTO propagation_edges VALUES (?,?,?,?,?,?)",
                (e["src"], e["dst"], e["edge_type"],
                 e.get("ts_src"), e.get("ts_dst"), e.get("evidence", "")))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


# --------------------------------------------------------------------------- #
def _row_to_post(row: sqlite3.Row) -> Post:
    media = [Media(**m) for m in json.loads(row["media"] or "[]")]
    return Post(
        post_id=row["post_id"],
        platform=row["platform"],
        account_id=row["account_id"],
        timestamp=iso_to_dt(row["timestamp"]),
        kind=row["kind"] or "post",
        text=row["text"] or "",
        lang=row["lang"],
        media=media,
        likes=row["likes"], shares=row["shares"], replies=row["replies"],
        views=row["views"], url=row["url"],
        reply_to=row["reply_to"], forward_from=row["forward_from"],
        quote_of=row["quote_of"], parent_id=row["parent_id"],
        relevance_score=row["relevance_score"] or 0.0,
        relevance_decision=row["relevance_decision"] or "unscored",
        relevance_reason=row["relevance_reason"] or "",
        relevance_signals=json.loads(row["relevance_signals"] or "{}"),
        is_generic=bool(row["is_generic"]),
        raw=json.loads(row["raw"] or "{}"),
    )


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=row["account_id"],
        platform=row["platform"],
        handle=row["handle"],
        display_name=row["display_name"],
        kind=row["kind"] or "user",
        description=row["description"],
        created_at=iso_to_dt(row["created_at"]),
        profile_photo_phash=row["profile_photo_phash"],
        profile_photo_url=row["profile_photo_url"],
        external_links=json.loads(row["external_links"] or "[]"),
        followers=row["followers"],
        raw=json.loads(row["raw"] or "{}"),
    )
