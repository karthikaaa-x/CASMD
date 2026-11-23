"""
Edge-case & limitation tests.

These do two jobs:
  1. GUARANTEES — assert the behaviours the tool promises (determinism, UTF-8
     safety, graceful handling of empty/odd input, correct import normalisation).
  2. DOCUMENTED LIMITATIONS — pin down the *known* edges so they can never
     regress silently. Where a limitation is intentional (e.g. an unparseable
     date falls back to "now"), the test asserts that documented behaviour and
     the docstring says it is a known limitation, not a bug.
"""

import os
import json
import csv
from datetime import datetime, timezone

import pytest

from casmd.config import Config, Incident
from casmd.run import run, DEMO_INCIDENT
from casmd.store import Store
from casmd.schema import Post, Account, Media, iso_to_dt
from casmd.collectors import import_data, synthetic


# --------------------------------------------------------------------------- #
# Date parsing
# --------------------------------------------------------------------------- #
def test_oldest_iso_date_year_one():
    """GUARANTEE: ISO dates parse back to year 1 (Python datetime.min)."""
    assert import_data.parse_dt("0001-01-01").year == 1
    assert import_data.parse_dt("1850-03-04").year == 1850


def test_iso_is_timezone_aware_utc():
    dt = import_data.parse_dt("2026-11-21T10:00:00Z")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_epoch_seconds_and_millis():
    """GUARANTEE: positive epoch in seconds or milliseconds is handled."""
    assert import_data.parse_dt("0").year == 1970
    # a realistic ms timestamp (~2026) must parse to 2026, not year 30000+
    ms = str(int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000))
    assert import_data.parse_dt(ms).year == 2026


def test_bad_dates_never_crash_and_fall_back_to_now():
    """LIMITATION (documented): unparseable dates, pre-1970 epochs (negative,
    which .isdigit() rejects), and out-of-range numbers do NOT raise — they fall
    back to the current time. Feeds with dirty timestamps should be cleaned
    before import, or those posts may land at collection time."""
    now_year = datetime.now(timezone.utc).year
    for bad in ("not a date", "", "May 5 2020", "-62135596800", "1000000000000"):
        dt = import_data.parse_dt(bad)
        assert dt.tzinfo is not None          # always tz-aware
        assert dt.year == now_year            # documented: falls back to now


def test_day_first_date_interpretation():
    """LIMITATION (documented): slash dates are read day-first (DD/MM/YYYY)."""
    assert import_data.parse_dt("13/05/1999 08:30").month == 5


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_pipeline_is_deterministic(tmp_path):
    """GUARANTEE: same data in -> byte-identical report out (no randomness)."""
    reports = []
    for i in range(2):
        cfg = Config(incident=DEMO_INCIDENT)
        cfg.db_path = str(tmp_path / f"db{i}.sqlite")
        cfg.out_dir = str(tmp_path / f"out{i}")
        run(cfg, reseed=True)
        reports.append(open(os.path.join(cfg.out_dir, "report.json"),
                            encoding="utf-8").read())
    assert reports[0] == reports[1]


# --------------------------------------------------------------------------- #
# UTF-8 / unicode safety (the Windows cp1252 bug class)
# --------------------------------------------------------------------------- #
def test_unicode_round_trips_through_store(tmp_path):
    """GUARANTEE: emoji / non-ASCII survive store write+read and JSON export."""
    db = str(tmp_path / "u.sqlite")
    s = Store(db)
    s.upsert_account(Account("yt:u", "youtube"))
    s.upsert_post(Post("yt:p", "youtube", "yt:u",
                       timestamp=datetime(2026, 11, 1, tzinfo=timezone.utc),
                       text="🚨 BRÈAKING 船 test"))
    s.commit()
    back = s.posts()[0]
    s.close()
    assert back.text == "🚨 BRÈAKING 船 test"


def test_exports_are_valid_utf8_json(tmp_path):
    cfg = Config(incident=DEMO_INCIDENT)
    cfg.db_path = str(tmp_path / "db.sqlite")
    cfg.out_dir = str(tmp_path / "out")
    run(cfg, reseed=True)
    for name in ("report.json", "posts.json", "media_clusters.json",
                 "narratives.json", "propagation_graph.json", "timeline.json"):
        with open(os.path.join(cfg.out_dir, name), encoding="utf-8") as f:
            json.load(f)   # raises if malformed


# --------------------------------------------------------------------------- #
# Empty / degenerate input
# --------------------------------------------------------------------------- #
def test_empty_database_stops_gracefully(tmp_path):
    """GUARANTEE: no posts -> a clear SystemExit, not a stack trace."""
    db = str(tmp_path / "empty.sqlite")
    Store(db).close()
    cfg = Config(incident=DEMO_INCIDENT)
    cfg.db_path = db
    cfg.out_dir = str(tmp_path / "out")
    with pytest.raises(SystemExit):
        run(cfg, reseed=False, analyze_only=True)


def test_single_platform_data_does_not_crash(tmp_path):
    """GUARANTEE: Telegram-only (or YouTube-only) data analyses fine; cross-
    platform detectors simply produce nothing."""
    db = str(tmp_path / "one.sqlite")
    s = Store(db)
    base = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
    for i in range(5):
        s.upsert_account(Account(f"tg:c{i}", "telegram", kind="channel"))
        s.upsert_post(Post(f"tg:m{i}", "telegram", f"tg:c{i}", kind="message",
                           timestamp=base, text="ship bombing vessel explosion news"))
    s.commit(); s.close()
    cfg = Config(incident=DEMO_INCIDENT)
    cfg.db_path = db
    cfg.out_dir = str(tmp_path / "out")
    run(cfg, reseed=False, analyze_only=True)   # must not raise
    assert os.path.exists(os.path.join(cfg.out_dir, "dashboard.html"))


# --------------------------------------------------------------------------- #
# Import normalisation
# --------------------------------------------------------------------------- #
def test_import_platform_prefixes_and_media_type(tmp_path):
    """GUARANTEE: imported YouTube/Telegram rows get yt:/tg: ids, and a row with
    a video fingerprint is typed as video even on Telegram."""
    csv_path = tmp_path / "d.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["platform", "post_id", "author",
            "created_at", "text", "kind", "video_url", "media_sha256"])
        w.writeheader()
        w.writerow({"platform": "youtube", "post_id": "1", "author": "chanA",
                    "created_at": "2026-11-05 09:00:00", "text": "ship bombing clip",
                    "kind": "video", "video_url": "https://youtube.com/watch?v=a",
                    "media_sha256": "abc123"})
        w.writerow({"platform": "telegram", "post_id": "5", "author": "chanB",
                    "created_at": "2026-11-05 11:00:00", "text": "ship bombing clip",
                    "kind": "message", "video_url": "https://t.me/chanB/5",
                    "media_sha256": "abc123"})
    db = str(tmp_path / "imp.sqlite")
    s = Store(db)
    import_data.load(str(csv_path), s, default_platform="youtube")
    posts = {p.post_id: p for p in s.posts()}
    s.close()
    assert "yt:1" in posts and "tg:5" in posts
    # telegram video fingerprint -> typed as video (so it clusters with the YT one)
    assert posts["tg:5"].media and posts["tg:5"].media[0].type == "video"


# --------------------------------------------------------------------------- #
# Core guarantees restated as explicit edge checks
# --------------------------------------------------------------------------- #
def test_no_media_no_false_strong_group(pipeline_topic):
    """GUARANTEE: a broad-topic dataset with reply chains and synchronized timing
    but NO shared media / captions yields NO 'strong' group (only possible/Low)."""
    strong = [g for g in pipeline_topic["groups"]
              if g["classification"] == "strong coordination indicators"]
    assert not strong, f"topic data produced false strong group(s): {strong}"


# --------------------------------------------------------------------------- #
# Fixture: a broad-topic (non-incident) dataset, built in memory
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def pipeline_topic():
    import random
    from casmd.analysis import (relevance, media as mm, narratives as nr,
                                coordination as co)
    rng = random.Random(5)
    inc = Incident(name="Topic", primary_keyword="ship bombing",
                   additional_keywords=["vessel explosion"],
                   date_start="2026-05-01", date_end="2026-08-01")
    cfg = Config(incident=inc)
    base = datetime(2026, 6, 1, 9, tzinfo=timezone.utc)
    accounts, posts, pid = {}, [], [0]

    def acc(a, **k):
        accounts[a] = Account(a, k.get("platform", "youtube"), **{x: v for x, v in k.items() if x != "platform"})
    vids = []
    for i in range(6):
        ch = f"yt:ch{i}"; acc(ch, platform="youtube", kind="channel")
        vp = f"yt:v{i}"; vids.append(vp)
        posts.append(Post(vp, "youtube", ch, kind="video",
                          timestamp=base, text="ship bombing vessel explosion clip number %d" % i,
                          media=[Media("video", media_id=f"m{i}")]))  # all DIFFERENT media
    users = [f"yt:u{i}" for i in range(20)]
    for u in users:
        acc(u, platform="youtube", kind="user")
    # Realistic organic comments: everyone words it differently (no verbatim
    # reuse), so there is no shared media and no near-identical caption — only
    # reply chains and coincidental timing. This is the real "broad topic" case.
    openers = ["is the", "anyone seen the", "what happened with the", "following the",
               "not sure about the", "my friend mentioned the", "why is nobody covering the",
               "just saw the", "cant believe the", "worried about the"]
    tails = ["ship bombing story", "vessel explosion footage", "maritime attack clip",
             "news going around today", "thing everyone is sharing", "report from this morning"]
    for k in range(60):
        pid[0] += 1
        vp = rng.choice(vids); u = rng.choice(users)
        txt = f"{openers[k % len(openers)]} {tails[(k // 2) % len(tails)]} number {k}"
        posts.append(Post(f"yt:c{pid[0]}", "youtube", u, kind="comment",
                          timestamp=base, text=txt, reply_to=vp, parent_id=vp))
    relevance.score_posts(inc, cfg, posts)
    assets = mm.build_assets(posts)
    clusters, p2c = mm.cluster(assets, cfg)
    relevance.apply_media_boost(cfg, posts, clusters)
    relevance.gate_comments(cfg, posts)
    rel = [p for p in posts if p.relevance_decision == "relevant"]
    narr = [p for p in rel if not p.is_generic]
    ns, _, pp = nr.detect(narr, cfg, p2c)
    groups, _, _ = co.detect(rel, accounts, cfg, media_clusters=clusters,
                             post_to_cluster=p2c, per_post_narr=pp)
    return {"groups": groups}
