"""
Origin & propagation analysis.

For the incident as a whole, and per narrative and per media cluster, this
reconstructs:
  * the earliest observed upload overall, and the earliest on each platform;
  * the first accounts/channels to distribute the media;
  * subsequent reuploads / forwards of the same media;
  * the first appearance of each distinct narrative;
  * the cross-platform propagation sequence;
  * a chronological event timeline;
  * a propagation graph (nodes = key posts, typed edges = relationships).

IMPORTANT caveat, surfaced everywhere: the earliest *collected* post is the
earliest OBSERVED activity, which is not necessarily the original source or the
true origin of the footage. The system is explicit about this distinction.
"""

from __future__ import annotations

from collections import defaultdict


def _card(p, coord_accounts):
    return {
        "post_id": p.post_id, "account_id": p.account_id, "platform": p.platform,
        "kind": p.kind, "timestamp": p.timestamp.isoformat(),
        "text": (p.text or "")[:160], "url": p.url,
        "coordinated": p.account_id in coord_accounts,
    }


def analyze(posts, per_post_narr, media_clusters, post_to_cluster, groups,
            narratives):
    coord_accounts = {a for g in groups
                      if g["classification"] != "insufficient evidence"
                      for a in g["account_ids"]}
    narr_label = {n["narrative_id"]: n for n in narratives}
    rel = [p for p in posts if p.relevance_decision == "relevant"]
    rel.sort(key=lambda p: p.timestamp)

    # ---- earliest observed ------------------------------------------------ #
    earliest = {"overall": _card(rel[0], coord_accounts) if rel else None,
                "per_platform": {}}
    seen_plat = {}
    for p in rel:
        if p.platform not in seen_plat:
            seen_plat[p.platform] = p
            earliest["per_platform"][p.platform] = _card(p, coord_accounts)

    # ---- per media cluster ------------------------------------------------ #
    by_post = {p.post_id: p for p in posts}
    media_origin = []
    for c in media_clusters:
        cposts = sorted((by_post[pid] for pid in c.post_ids if pid in by_post),
                        key=lambda p: p.timestamp)
        if not cposts:
            continue
        media_origin.append({
            "cluster_id": c.cluster_id, "confidence": c.confidence,
            "match_types": c.match_types, "platforms": c.platforms,
            "num_accounts": len(c.account_ids),
            "first_observed": _card(cposts[0], coord_accounts),
            "sequence": [_card(p, coord_accounts) for p in cposts[:12]],
        })

    # ---- per narrative ---------------------------------------------------- #
    narr_posts = defaultdict(list)
    for p in rel:
        nid = per_post_narr.get(p.post_id, -1)
        if nid != -1:
            narr_posts[nid].append(p)
    per_narrative = []
    for nid, plist in narr_posts.items():
        plist.sort(key=lambda p: p.timestamp)
        first_seen = {}
        for p in plist:
            first_seen.setdefault(p.platform, p)
        spread_path = [{"platform": plat, "first_seen": pp.timestamp.isoformat()}
                       for plat, pp in sorted(first_seen.items(),
                                              key=lambda kv: kv[1].timestamp)]
        coord_share = round(sum(1 for p in plist
                                if p.account_id in coord_accounts) / len(plist), 2)
        per_narrative.append({
            "narrative_id": nid,
            "label": narr_label.get(nid, {}).get("label", ""),
            "stance": narr_label.get(nid, {}).get("stance", ""),
            "summary": narr_label.get(nid, {}).get("claim_summary", ""),
            "total_posts": len(plist),
            "coordinated_share": coord_share,
            "earliest": _card(plist[0], coord_accounts),
            "seeders": [_card(p, coord_accounts) for p in plist[:5]],
            "spread_path": spread_path,
        })
    per_narrative.sort(key=lambda r: -r["coordinated_share"])

    # ---- propagation graph + edges + timeline ----------------------------- #
    edges = []
    nodes = {}

    def node(p):
        if p.post_id not in nodes:
            nd = _card(p, coord_accounts)
            nd["media_cluster"] = post_to_cluster.get(p.post_id)
            nd["narrative"] = per_post_narr.get(p.post_id, -1)
            nodes[p.post_id] = nd
        return p.post_id

    # media reuploads: earliest asset in a cluster -> each later appearance
    for c in media_clusters:
        cposts = sorted((by_post[pid] for pid in c.post_ids if pid in by_post),
                        key=lambda p: p.timestamp)
        if len(cposts) < 2:
            continue
        origin = cposts[0]
        node(origin)
        for later in cposts[1:]:
            node(later)
            same_acct = later.account_id == origin.account_id
            if same_acct:
                continue
            etype = ("cross_platform_media" if later.platform != origin.platform
                     else "media_reupload")
            edges.append({
                "src": origin.post_id, "dst": later.post_id, "edge_type": etype,
                "ts_src": origin.timestamp.isoformat(),
                "ts_dst": later.timestamp.isoformat(),
                "evidence": f"same media (cluster #{c.cluster_id}, {c.confidence})"})

    # telegram forwards / quotes
    first_by_acct = {}
    for p in rel:
        first_by_acct.setdefault(p.account_id, p)
    for p in rel:
        if p.forward_from and p.forward_from in first_by_acct:
            src = first_by_acct[p.forward_from]
            node(src)
            node(p)
            edges.append({
                "src": src.post_id, "dst": p.post_id, "edge_type": "telegram_forward",
                "ts_src": src.timestamp.isoformat(),
                "ts_dst": p.timestamp.isoformat(),
                "evidence": f"forwarded from {p.forward_from}"})

    # narrative variants: incident origin -> earliest post of each narrative
    if rel:
        origin_post = rel[0]
        node(origin_post)
        for r in per_narrative:
            earliest_card = r["earliest"]
            ep = by_post.get(earliest_card["post_id"])
            if ep and ep.post_id != origin_post.post_id:
                node(ep)
                edges.append({
                    "src": origin_post.post_id, "dst": ep.post_id,
                    "edge_type": "narrative_variant",
                    "ts_src": origin_post.timestamp.isoformat(),
                    "ts_dst": ep.timestamp.isoformat(),
                    "evidence": f"narrative '{r['label']}' first appears"})

    # timeline: notable events, chronological
    timeline = []
    if earliest["overall"]:
        timeline.append({**earliest["overall"], "event": "earliest observed post"})
    for mo in media_origin:
        timeline.append({**mo["first_observed"],
                         "event": f"media cluster #{mo['cluster_id']} first observed "
                                  f"({mo['confidence']} confidence)"})
    for r in per_narrative:
        timeline.append({**r["earliest"],
                         "event": f"narrative '{r['label']}' first appears"})
    for e in edges:
        if e["edge_type"] in ("cross_platform_media", "telegram_forward"):
            src_node = nodes.get(e["dst"])
            if src_node:
                timeline.append({**src_node, "event": e["edge_type"].replace("_", " ")})
    # dedup + sort
    seen = set()
    uniq_tl = []
    for ev in sorted(timeline, key=lambda e: e["timestamp"]):
        k = (ev["post_id"], ev["event"])
        if k not in seen:
            seen.add(k)
            uniq_tl.append(ev)

    return {
        "note": ("Earliest OBSERVED activity, not necessarily the original "
                 "source. The earliest collected post may be a reupload; the "
                 "true origin of the footage cannot be established from "
                 "collected data alone."),
        "earliest": earliest,
        "media_origin": media_origin,
        "per_narrative": per_narrative,
        "timeline": uniq_tl,
        "graph": {"nodes": list(nodes.values()), "edges": edges},
        "edges": edges,
    }
