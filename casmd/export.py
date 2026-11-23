"""Export analysis results. Produces every file the brief requires:

    report.json              full combined report
    posts.json / posts.csv   all collected posts (with relevance + narrative)
    coordinated_groups.csv   one row per coordinated group
    media_clusters.json      media correlation clusters
    narratives.json          narrative groups with stance
    propagation_graph.json   propagation nodes + typed edges
    timeline.json            chronological incident timeline

All relationships (post<->account<->narrative<->media<->group) are preserved.
"""

from __future__ import annotations

import os
import json
import csv


def _w(out_dir, name, obj):
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


def export_all(cfg, posts, accounts, narratives, per_post, groups,
               media_clusters, prop):
    out_dir = cfg.out_dir
    inc = cfg.incident
    os.makedirs(out_dir, exist_ok=True)

    # post -> group id (only non-insufficient groups)
    post_group = {}
    acct_group = {}
    for g in groups:
        if g["classification"] == "insufficient evidence":
            continue
        for a in g["account_ids"]:
            acct_group[a] = g["group_id"]
    for p in posts:
        if p.account_id in acct_group:
            post_group[p.post_id] = acct_group[p.account_id]

    # media cluster per post
    post_cluster = {}
    for c in media_clusters:
        for pid in c.post_ids:
            post_cluster[pid] = c.cluster_id

    # ---- posts.csv -------------------------------------------------------- #
    with open(os.path.join(out_dir, "posts.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["post_id", "platform", "kind", "account_id", "timestamp",
                    "relevance_score", "relevance_decision", "is_generic",
                    "narrative_id", "media_cluster", "coord_group",
                    "likes", "shares", "replies", "views", "url", "photos",
                    "videos", "text"])
        for p in posts:
            photos = "|".join(m.url for m in p.media if m.type == "image" and m.url)
            videos = "|".join(m.url for m in p.media if m.type == "video" and m.url)
            w.writerow([p.post_id, p.platform, p.kind, p.account_id,
                        p.timestamp.isoformat(), round(p.relevance_score, 3),
                        p.relevance_decision, int(p.is_generic),
                        per_post.get(p.post_id, -1),
                        post_cluster.get(p.post_id, ""),
                        post_group.get(p.post_id, ""),
                        p.likes, p.shares, p.replies, p.views, p.url,
                        photos, videos, p.text])

    # ---- posts.json ------------------------------------------------------- #
    _w(out_dir, "posts.json", [{
        "post_id": p.post_id, "platform": p.platform, "kind": p.kind,
        "account_id": p.account_id, "timestamp": p.timestamp.isoformat(),
        "relevance": {"score": round(p.relevance_score, 3),
                      "decision": p.relevance_decision,
                      "reason": p.relevance_reason,
                      "signals": p.relevance_signals, "is_generic": p.is_generic},
        "narrative_id": per_post.get(p.post_id, -1),
        "media_cluster": post_cluster.get(p.post_id),
        "coord_group": post_group.get(p.post_id),
        "text": p.text, "lang": p.lang,
        "engagement": {"likes": p.likes, "shares": p.shares,
                       "replies": p.replies, "views": p.views},
        "url": p.url,
        "media": [m.to_dict() for m in p.media],
        "refs": {"reply_to": p.reply_to, "forward_from": p.forward_from,
                 "quote_of": p.quote_of, "parent_id": p.parent_id},
    } for p in posts])

    # ---- coordinated_groups.csv ------------------------------------------ #
    with open(os.path.join(out_dir, "coordinated_groups.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "classification", "confidence", "num_accounts",
                    "score", "detectors", "account_ids", "evidence"])
        for g in groups:
            w.writerow([g["group_id"], g["classification"], g["confidence"],
                        len(g["account_ids"]), g["score"],
                        "|".join(g["detectors"]), "|".join(g["account_ids"]),
                        g["evidence"]])

    # ---- media_clusters.json --------------------------------------------- #
    _w(out_dir, "media_clusters.json", [{
        "cluster_id": c.cluster_id, "confidence": c.confidence,
        "match_types": c.match_types, "sha256": c.sha256, "phash": c.phash,
        "platforms": c.platforms, "num_accounts": len(set(c.account_ids)),
        "account_ids": c.account_ids, "post_ids": c.post_ids,
        "asset_ids": c.asset_ids,
        "first_observed": c.first_observed.isoformat() if c.first_observed else None,
        "evidence": c.evidence,
    } for c in media_clusters])

    # ---- narratives.json -------------------------------------------------- #
    _w(out_dir, "narratives.json", narratives)

    # ---- propagation_graph.json ------------------------------------------ #
    _w(out_dir, "propagation_graph.json", prop["graph"])

    # ---- timeline.json ---------------------------------------------------- #
    _w(out_dir, "timeline.json", prop["timeline"])

    # ---- report.json (combined) ------------------------------------------ #
    coord_real = [g for g in groups if g["classification"] != "insufficient evidence"]
    report = {
        "incident": {
            "name": inc.name, "primary_keyword": inc.primary_keyword,
            "additional_keywords": inc.additional_keywords,
            "description": inc.description,
            "date_range": f"{inc.date_start} … {inc.date_end}",
            "platforms": list(inc.platforms),
        },
        "summary": {
            "total_collected": len(posts),
            "relevant_posts": sum(1 for p in posts if p.relevance_decision == "relevant"),
            "review_posts": sum(1 for p in posts if p.relevance_decision == "review"),
            "irrelevant_posts": sum(1 for p in posts if p.relevance_decision == "irrelevant"),
            "total_accounts": len(accounts),
            "num_narratives": len(narratives),
            "num_media_clusters": len(media_clusters),
            "num_coordinated_groups": len(coord_real),
            "coordinated_accounts": sorted(
                {a for g in coord_real for a in g["account_ids"]}),
        },
        "narratives": narratives,
        "media_clusters": [c.__dict__ for c in media_clusters],
        "coordinated_groups": groups,
        "propagation": {"note": prop["note"], "earliest": prop["earliest"],
                        "media_origin": prop["media_origin"],
                        "per_narrative": prop["per_narrative"]},
        "timeline": prop["timeline"],
    }
    _w(out_dir, "report.json", report)
    return report
