"""
Per-narrative and per-group insight: turns clusters and groups into readable
findings for the dashboard and report.
"""

from __future__ import annotations

from collections import defaultdict, Counter

from . import entities, sentiment


def post_card(p, per_post_narr, coord_accounts, post_to_cluster=None):
    post_to_cluster = post_to_cluster or {}
    thumb = next((m.url for m in p.media if m.type == "image" and m.url), None)
    has_video = any(m.type == "video" for m in p.media)
    return {
        "post_id": p.post_id, "platform": p.platform, "kind": p.kind,
        "account_id": p.account_id,
        "coordinated": p.account_id in coord_accounts,
        "timestamp": p.timestamp.isoformat(),
        "text": (p.text or "")[:300], "url": p.url, "thumb": thumb,
        "has_video": has_video,
        "likes": p.likes, "shares": p.shares, "replies": p.replies, "views": p.views,
        "narrative_id": per_post_narr.get(p.post_id, -1),
        "media_cluster": post_to_cluster.get(p.post_id),
        "relevance_score": round(p.relevance_score, 2),
        "relevance_decision": p.relevance_decision,
        "is_generic": p.is_generic,
    }


# keep a short alias used internally
_post_card = post_card


def narrative_insights(posts, per_post_narr, narratives, coord_accounts,
                       post_to_cluster=None):
    by_narr = defaultdict(list)
    for p in posts:
        nid = per_post_narr.get(p.post_id, -1)
        if nid != -1:
            by_narr[nid].append(p)

    out = {}
    for n in narratives:
        nid = n["narrative_id"]
        plist = by_narr.get(nid, [])
        if not plist:
            continue
        senti = [sentiment.score(p.text) for p in plist]
        avg = sum(senti) / len(senti)

        acct_counts = Counter(p.account_id for p in plist)
        top_accounts = [{"account_id": a, "posts": c,
                         "coordinated": a in coord_accounts}
                        for a, c in acct_counts.most_common(6)]

        hashtags, domains = Counter(), Counter()
        for p in plist:
            e = entities.extract(p.text)
            hashtags.update(e["hashtags"])
            domains.update(e["domains"])

        ranked = sorted(plist, key=lambda p: -(p.likes + p.shares + p.views))
        examples, seen = [], set()
        for p in ranked:
            key = (p.text or "")[:60].lower()
            if key in seen:
                continue
            seen.add(key)
            examples.append(post_card(p, per_post_narr, coord_accounts,
                                      post_to_cluster))
            if len(examples) >= 4:
                break

        coord_share = round(sum(1 for p in plist
                                if p.account_id in coord_accounts) / len(plist), 2)
        plat = Counter(p.platform for p in plist)

        out[nid] = {
            "mood": sentiment.label(avg),
            "mood_score": round(avg, 2),
            "top_accounts": top_accounts,
            "top_hashtags": [h for h, _ in hashtags.most_common(6)],
            "top_domains": [d for d, _ in domains.most_common(6)],
            "coordinated_share": coord_share,
            "platform_breakdown": dict(plat),
            "examples": examples,
        }
    return out


def group_example_posts(posts, coord_groups, per_post_narr, coord_accounts,
                        post_to_cluster=None, max_per_group=8):
    by_acct = defaultdict(list)
    for p in posts:
        by_acct[p.account_id].append(p)
    out = {}
    for g in coord_groups:
        cards = []
        for aid in g["account_ids"]:
            for p in sorted(by_acct.get(aid, []), key=lambda p: p.timestamp):
                cards.append(post_card(p, per_post_narr, coord_accounts,
                                       post_to_cluster))
        cards.sort(key=lambda c: (c["text"] or "")[:40].lower())
        out[g["group_id"]] = cards[:max_per_group]
    return out
