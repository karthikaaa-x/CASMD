"""
CASMD orchestrator — incident-centric pipeline.

Usage
-----
Synthetic demonstration (no credentials, deterministic):
    python -m casmd.run --demo

Live collection (YouTube + Telegram; needs free API credentials):
    python -m casmd.run --live \
        --incident "Ship bombing deepfake incident" \
        --primary "ship bombing" \
        --keywords "vessel explosion,ship attacked,maritime attack,naval bombing" \
        --description "A possibly manipulated video of a ship being bombed is circulating." \
        --start 2026-11-01 --end 2026-11-20

Import a dataset someone hands you (CSV/JSON), then analyze:
    python -m casmd.run --import their_posts.csv --platform youtube \
        --primary "ship bombing" --start 2026-11-01 --end 2026-11-20

Analyze whatever is already in the DB:
    python -m casmd.run --analyze-only --primary "ship bombing" ...

Pipeline (the central principle in action):
    collect -> RELEVANCE (is this the same incident?) -> media correlation ->
    narratives -> coordination (only over relevant content) -> origin/propagation
    -> exports + dashboard
"""

from __future__ import annotations

import os
import argparse
from datetime import datetime, timezone

from .config import Config, Incident, SUPPORTED_PLATFORMS
from .store import Store
from .schema import iso_to_dt
from .analysis import relevance, media as media_mod, narratives as narr
from .analysis import coordination as coord, origin as origin_mod, insight
from .export import export_all
from .dashboard import build as build_dashboard


def run(cfg: Config, reseed=False, imports=None, analyze_only=False,
        live=False, tg_channels=None, tg_search=True, apply_date_filter=True,
        nicegram=False, nicegram_bot=None):
    inc = cfg.incident
    os.makedirs(os.path.dirname(cfg.db_path), exist_ok=True)
    store = Store(cfg.db_path)
    if reseed or imports or live:
        store.reset()

    # ---- collection ------------------------------------------------------- #
    if reseed:
        from .collectors import synthetic
        synthetic.build(store, inc)
    if imports:
        from .collectors import import_data
        for path, platform in imports:
            import_data.load(path, store, default_platform=platform or "youtube")
    if live:
        from .collectors import live as live_collector
        total, used = live_collector.collect(inc, cfg, store,
                                             tg_channels=tg_channels,
                                             tg_search=tg_search,
                                             nicegram=nicegram,
                                             nicegram_bot=nicegram_bot)
        print(f"[live] collected {total} posts from: {', '.join(used) or 'nothing'}")
        if total == 0:
            store.close()
            raise SystemExit(
                "Live collection returned 0 posts. Set free API credentials "
                "(YT_API_KEY, TG_API_ID/TG_API_HASH) — see README — or use --demo.")

    store.save_incident(inc)
    posts = store.posts()
    accounts = store.accounts()

    # ---- date filter ------------------------------------------------------ #
    def _utc(dt):
        return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt
    start = _utc(iso_to_dt(inc.date_start)) if apply_date_filter else None
    end = _utc(iso_to_dt(inc.date_end + "T23:59:59")) if apply_date_filter else None
    if start or end:
        before = len(posts)
        posts = [p for p in posts
                 if (not start or _utc(p.timestamp) >= start)
                 and (not end or _utc(p.timestamp) <= end)]
        if before != len(posts):
            print(f"[filter] date range kept {len(posts)}/{before} posts")
    if not posts:
        store.close()
        raise SystemExit("No posts to analyze. Check --import / dates / --demo.")

    print(f"[incident] '{inc.name}' — {len(posts)} posts, {len(accounts)} accounts")

    # ---- 1) RELEVANCE ----------------------------------------------------- #
    rstats = relevance.score_posts(inc, cfg, posts)
    print(f"[relevance] relevant={rstats['relevant']} review={rstats['review']} "
          f"irrelevant={rstats['irrelevant']} (generic={rstats['generic']})")

    # ---- 2) MEDIA correlation (over all posts, to catch reuploads) -------- #
    assets = media_mod.build_assets(posts)
    media_clusters, post_to_cluster = media_mod.cluster(assets, cfg)
    promoted = relevance.apply_media_boost(cfg, posts, media_clusters)
    if promoted:
        print(f"[relevance] promoted {promoted} post(s) via shared-media evidence")
    # Gate YouTube comments now that parent videos have their final relevance.
    rstats = relevance.gate_comments(cfg, posts)
    print(f"[relevance] after media boost + comment gating: "
          f"relevant={rstats['relevant']} irrelevant={rstats['irrelevant']}")
    for p in posts:
        store.update_post_relevance(p)
    store.commit()
    store.save_media_clusters(media_clusters)
    print(f"[media] {len(media_clusters)} media cluster(s) "
          f"(shared across >=2 accounts: "
          f"{sum(1 for c in media_clusters if len(set(c.account_ids)) >= 2)})")

    # ---- narrow to the incident dataset ----------------------------------- #
    rel_posts = [p for p in posts if p.relevance_decision == "relevant"]
    narr_posts = [p for p in rel_posts if not p.is_generic]
    # comments only join coordination if they carry real incident content
    coord_posts = [p for p in rel_posts if not (
        p.kind == "comment" and p.relevance_score < cfg.comment_min_relevance_for_coord)]
    print(f"[incident] {len(rel_posts)} relevant posts admitted "
          f"({len(coord_posts)} eligible for coordination analysis)")

    # ---- 3) NARRATIVES ---------------------------------------------------- #
    narratives, assignments, per_post = narr.detect(narr_posts, cfg, post_to_cluster)
    store.save_narratives(narratives, assignments)
    vol_time = narr.volume_over_time(narr_posts, per_post)
    vol_plat = narr.volume_per_platform(narr_posts, per_post)
    print(f"[narratives] {len(narratives)} narrative(s)")

    # ---- 4) COORDINATION (incident-centric) ------------------------------- #
    groups, G, directed = coord.detect(coord_posts, accounts, cfg,
                                       media_clusters=media_clusters,
                                       post_to_cluster=post_to_cluster,
                                       per_post_narr=per_post)
    store.save_coord_groups(groups)
    coord_accounts = {a for g in groups
                      if g["classification"] != "insufficient evidence"
                      for a in g["account_ids"]}
    strong = sum(1 for g in groups if g["classification"] == "strong coordination indicators")
    possible = sum(1 for g in groups if g["classification"] == "possible coordination indicators")
    print(f"[coordination] {strong} strong, {possible} possible group(s); "
          f"{len(coord_accounts)} flagged accounts")

    # ---- insight ---------------------------------------------------------- #
    insights = insight.narrative_insights(narr_posts, per_post, narratives,
                                          coord_accounts, post_to_cluster)
    for n in narratives:
        n.update(insights.get(n["narrative_id"], {}))
        n["volume_over_time"] = vol_time.get(n["narrative_id"], {})
        n["volume_per_platform"] = vol_plat.get(n["narrative_id"], {})
    g_examples = insight.group_example_posts(coord_posts, groups, per_post,
                                             coord_accounts, post_to_cluster)
    for g in groups:
        g["example_posts"] = g_examples.get(g["group_id"], [])

    # ---- 5) ORIGIN + PROPAGATION ----------------------------------------- #
    prop = origin_mod.analyze(rel_posts, per_post, media_clusters, post_to_cluster,
                              groups, narratives)
    store.save_propagation(prop["edges"])

    # ---- exports + dashboard --------------------------------------------- #
    report = export_all(cfg, posts, accounts, narratives, per_post, groups,
                        media_clusters, prop)
    payload = _dashboard_payload(cfg, posts, rel_posts, accounts, narratives,
                                 per_post, groups, media_clusters, prop,
                                 coord_accounts, post_to_cluster, rstats)
    dash = build_dashboard(payload, os.path.join(cfg.out_dir, "dashboard.html"))

    store.close()
    print("[done] wrote:")
    for f in ("report.json", "posts.json", "posts.csv", "coordinated_groups.csv",
              "media_clusters.json", "narratives.json", "propagation_graph.json",
              "timeline.json"):
        print(f"  {os.path.join(cfg.out_dir, f)}")
    print(f"  {dash}")
    return report


# --------------------------------------------------------------------------- #
def _dashboard_payload(cfg, posts, rel_posts, accounts, narratives, per_post,
                       groups, media_clusters, prop, coord_accounts,
                       post_to_cluster, rstats):
    inc = cfg.incident
    plat_counts = {}
    for p in rel_posts:
        plat_counts[p.platform] = plat_counts.get(p.platform, 0) + 1

    def best_name(a):
        return (a.display_name or a.handle or a.account_id.split(":", 1)[-1]).strip()
    acct_map = {aid: {"name": best_name(a), "handle": a.handle,
                      "platform": a.platform, "kind": a.kind,
                      "followers": a.followers}
                for aid, a in accounts.items()}

    post_cards = [insight.post_card(p, per_post, coord_accounts, post_to_cluster)
                  for p in sorted(rel_posts, key=lambda p: -(p.likes + p.views))][:1500]

    media_cards = [{
        "cluster_id": c.cluster_id, "confidence": c.confidence,
        "match_types": c.match_types, "platforms": c.platforms,
        "num_accounts": len(set(c.account_ids)), "num_posts": len(c.post_ids),
        "post_ids": c.post_ids, "account_ids": c.account_ids,
        "first_observed": c.first_observed.isoformat() if c.first_observed else None,
        "evidence": c.evidence,
        "thumb": _cluster_thumb(c, posts),
    } for c in media_clusters]

    strong = sum(1 for g in groups if g["classification"] == "strong coordination indicators")
    possible = sum(1 for g in groups if g["classification"] == "possible coordination indicators")

    return {
        "meta": {"incident": inc.name, "primary_keyword": inc.primary_keyword,
                 "keywords": inc.all_keywords(), "description": inc.description,
                 "date_start": inc.date_start, "date_end": inc.date_end,
                 "generated": datetime.now(timezone.utc).isoformat(),
                 "platforms": sorted(plat_counts)},
        "summary": {
            "total_collected": len(posts),
            "relevant_posts": len(rel_posts),
            "youtube_posts": plat_counts.get("youtube", 0),
            "telegram_posts": plat_counts.get("telegram", 0),
            "unique_accounts": len({p.account_id for p in rel_posts}),
            "num_media_clusters": len(media_clusters),
            "num_narratives": len(narratives),
            "num_strong_groups": strong,
            "num_possible_groups": possible,
            "flagged_accounts": len(coord_accounts),
            "relevance": rstats,
        },
        "risk": _risk(groups, coord_accounts, len(media_clusters), len(rel_posts)),
        "narratives": narratives,
        "groups": groups,
        "media_clusters": media_cards,
        "propagation": prop,
        "posts": post_cards,
        "accounts": acct_map,
    }


def _cluster_thumb(c, posts):
    by_id = {p.post_id: p for p in posts}
    for pid in c.post_ids:
        p = by_id.get(pid)
        if not p:
            continue
        for m in p.media:
            if m.type == "image" and m.url:
                return m.url
    return None


def _scope_hint(media_count, relevant):
    """A plain-language nudge when the input behaves like a broad topic rather
    than a bounded incident (what makes the whole dashboard legible)."""
    if media_count == 0:
        return (" No shared media was found circulating across accounts, so this "
                "looks more like a broad topic than a bounded incident. For a "
                "clearer picture, narrow the keyword to a specific event, claim "
                "or video, and tighten the date range to when it happened — the "
                "way the ship-bombing demo is scoped.")
    return ""


def _risk(groups, coord_accounts, media_count=0, relevant=0):
    real = [g for g in groups if g["classification"] != "insufficient evidence"]
    strong = [g for g in real if g["classification"] == "strong coordination indicators"]
    hint = _scope_hint(media_count, relevant)
    if not real:
        return {"level": "None",
                "headline": "No coordinated dissemination detected",
                "explain": "No group of accounts shared incident media or near-"
                           "identical claims with corroborating signals. Temporal "
                           "proximity alone was not treated as coordination." + hint}
    if not strong:
        # only low-confidence "possible" leads
        return {"level": "Medium",
                "headline": "Weak signals only — no strong coordination",
                "explain": f"{len(real)} low-confidence lead(s) "
                           f"({len(coord_accounts)} accounts) from amplification / "
                           f"synchronized timing, with no shared media or "
                           f"near-identical claims to corroborate them. Likely "
                           f"organic." + hint}
    return {
        "level": "High",
        "headline": f"Coordinated dissemination detected: {len(coord_accounts)} "
                    f"accounts across {len(real)} group(s)",
        "explain": f"{len(strong)} group(s) show strong coordination indicators "
                   f"(shared media / near-identical claims with corroboration). "
                   f"Treat as leads for review, not proof." + hint,
    }


# --------------------------------------------------------------------------- #
DEMO_INCIDENT = Incident(
    name="Ship bombing deepfake incident",
    primary_keyword="ship bombing",
    additional_keywords=["vessel explosion", "ship attacked", "maritime attack",
                         "naval bombing", "Iranian ship", "cargo vessel explosion"],
    description=("A potentially manipulated video depicting a ship being bombed is "
                 "circulating online. Identify the original or earliest observed "
                 "upload, subsequent reuploads, associated claims and coordinated "
                 "dissemination."),
    date_start="2026-11-01", date_end="2026-11-20")


def _build_incident(args) -> Incident:
    # --demo with no overrides uses the canonical ship-bombing incident.
    if args.demo and not args.primary and not args.incident:
        inc = Incident(**{**DEMO_INCIDENT.__dict__})
        if args.start:
            inc.date_start = args.start
        if args.end:
            inc.date_end = args.end
        return inc
    plats = tuple(p for p in (args.platforms or list(SUPPORTED_PLATFORMS))
                  if p in SUPPORTED_PLATFORMS) or SUPPORTED_PLATFORMS
    inc = Incident(
        name=args.incident or "Untitled incident",
        primary_keyword=args.primary or "",
        additional_keywords=[k.strip() for k in (args.keywords or "").split(",")
                             if k.strip()],
        description=args.description or "",
        date_start=args.start or Incident.date_start,
        date_end=args.end or Incident.date_end,
        platforms=plats)
    return inc


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CASMD — incident-centric SOCMINT")
    ap.add_argument("--demo", action="store_true",
                    help="generate the synthetic ship-bombing incident and analyze")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--live", action="store_true",
                    help="collect from YouTube + Telegram (needs credentials)")
    ap.add_argument("--import", dest="imports", action="append", default=[],
                    metavar="FILE", help="import a CSV/JSON dataset (repeatable)")
    ap.add_argument("--platform", action="append", default=[],
                    help="default platform for the matching --import file")
    ap.add_argument("--incident", default=None, help="incident name")
    ap.add_argument("--primary", default=None, help="primary keyword / phrase")
    ap.add_argument("--keywords", default=None, help="additional keywords (comma-sep)")
    ap.add_argument("--description", default=None, help="incident description")
    ap.add_argument("--start", default=None, help="date range start YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="date range end YYYY-MM-DD")
    ap.add_argument("--platforms", action="append", default=[],
                    help="youtube and/or telegram (repeatable)")
    ap.add_argument("--channels", default=None,
                    help="telegram channels to search (comma-separated)")
    ap.add_argument("--tg-all", action="store_true",
                    help="Telegram: pull ALL messages from --channels (ignore keyword)")
    ap.add_argument("--nicegram", action="store_true",
                    help="HIGHER RISK: drive a Telegram search bot via your "
                         "account for near-global search (use a burner account)")
    ap.add_argument("--nicegram-bot", default=None,
                    help="the search bot @username (or set NICEGRAM_BOT)")
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    live = args.live or args.nicegram          # --nicegram implies live collection
    inc = _build_incident(args)
    # Live with no dates: last 14 days.
    if live and not args.start and not args.end:
        from datetime import date, timedelta
        inc.date_end = date.today().isoformat()
        inc.date_start = (date.today() - timedelta(days=14)).isoformat()
        print(f"[live] no dates given; using {inc.date_start}..{inc.date_end}")

    cfg = Config(incident=inc)
    if args.db:
        cfg.db_path = args.db
    if args.out:
        cfg.out_dir = args.out

    imports = [(f, args.platform[i] if i < len(args.platform) else None)
               for i, f in enumerate(args.imports)]
    reseed = args.demo or (not args.analyze_only and not imports and not live)
    run(cfg, reseed=reseed, imports=imports or None,
        analyze_only=args.analyze_only, live=live,
        tg_channels=args.channels.split(",") if args.channels else None,
        tg_search=not args.tg_all,
        nicegram=args.nicegram, nicegram_bot=args.nicegram_bot,
        apply_date_filter=True)
