"""
Coordination detection — rebuilt to be INCIDENT-CENTRIC.

The old engine's fatal flaw: accounts could be linked purely because they posted
within a short time window, which produced spurious "coordinated" groups the
moment generic comments were collected. This version fixes that at the root.

Two hard rules enforced structurally:
  1. Only incident-RELEVANT posts participate (the caller passes relevant posts;
     generic posts are additionally excluded from the content detectors).
  2. Temporal proximity is NEVER, on its own, evidence of coordination. A
     synchronized-posting event is counted only when the two posts also share
     real content — the same media cluster, the same narrative, or near-identical
     text. Account-similarity signals (creation time, avatar, handle) are
     SUPPORTING only and can never, by themselves, create a link.

Detectors (from the brief)
  A shared_media        : accounts posting the same / near-identical media
  B near_dup_caption    : accounts posting near-identical incident captions
  C sync_dissemination  : accounts repeatedly posting the same media/narrative
                          within a short interval (content-gated, see rule 2)
  D cross_platform      : the same media/caption appearing on YouTube AND Telegram
  E account_similarity  : creation burst / avatar reuse / similar handles / shared
                          links (SUPPORTING only)
  F amplification       : Telegram forwards, repeated forwarding, YT reply chains

Fusion: build a weighted account-account graph; every edge records which
detectors fired and why. An edge is kept only if it carries at least one CONTENT
detector (A–D or F) and reaches a minimum fused weight. Connected components
become candidate groups, each classified as:

    strong coordination indicators | possible coordination indicators |
    insufficient evidence

with a High/Medium/Low confidence whose calculation is spelled out, and a full,
human-readable evidence trail.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

import networkx as nx

from . import textvec, entities
from ..utils import hamming, str_similarity, normalize_text

_CONF_FACTOR = {"high": 1.0, "medium": 0.6, "low": 0.4}
_COMMON_DOMAINS = {
    "youtube.com", "youtu.be", "t.me", "telegram.me", "twitter.com", "x.com",
    "instagram.com", "facebook.com", "tiktok.com", "google.com",
    "wikipedia.org", "reddit.com",
}


# --------------------------------------------------------------------------- #
# A. shared media
# --------------------------------------------------------------------------- #
def detect_shared_media(posts, media_clusters, cfg):
    by_cluster = {c.cluster_id: c for c in media_clusters}
    post_acct = {p.post_id: p.account_id for p in posts}
    edges = {}
    for c in media_clusters:
        accts = sorted({post_acct[pid] for pid in c.post_ids if pid in post_acct})
        if len(accts) < 2:
            continue
        w = cfg.detector_weights["shared_media"] * _CONF_FACTOR.get(c.confidence, 0.4)
        for a, b in combinations(accts, 2):
            key = tuple(sorted((a, b)))
            if key not in edges or edges[key]["weight"] < w:
                edges[key] = {
                    "weight": w,
                    "detail": f"posted the same media (cluster #{c.cluster_id}, "
                              f"{', '.join(c.match_types)}, {c.confidence} confidence)",
                    "cluster_id": c.cluster_id}
    return edges, by_cluster


# --------------------------------------------------------------------------- #
# B. near-duplicate captions (non-generic, incident-relevant only)
# --------------------------------------------------------------------------- #
def _dup_pairs(posts, cfg):
    """Return {(i,j): sim} for post index pairs with near-identical text, plus
    the filtered post list they index into."""
    # Only substantive, non-generic text is eligible: short reused phrases
    # collide among genuine fans and are not coordination evidence.
    cand = [p for p in posts if not p.is_generic
            and len(normalize_text(p.text).split()) >= cfg.min_caption_tokens]
    if len(cand) < 2:
        return {}, cand
    X, _ = textvec.tfidf([p.text for p in cand], analyzer="char",
                         ngram_range=(3, 5), min_df=1)
    sim = textvec.cosine_matrix(X)
    pairs = {}
    n = len(cand)
    for i in range(n):
        for j in range(i + 1, n):
            if cand[i].account_id == cand[j].account_id:
                continue
            if sim[i, j] >= cfg.text_sim_threshold:
                pairs[(i, j)] = float(sim[i, j])
    return pairs, cand


def detect_near_dup_caption(posts, cfg, dup_pairs=None, cand=None):
    if dup_pairs is None:
        dup_pairs, cand = _dup_pairs(posts, cfg)
    pair_count = defaultdict(int)
    examples = {}
    for (i, j), s in dup_pairs.items():
        key = tuple(sorted((cand[i].account_id, cand[j].account_id)))
        pair_count[key] += 1
        examples.setdefault(key, (cand[i].text[:70], round(s, 2)))
    edges = {}
    for key, c in pair_count.items():
        if c >= cfg.min_shared_dupes:
            ex, s = examples[key]
            edges[key] = {"weight": cfg.detector_weights["near_dup_caption"],
                          "detail": f"{c} near-identical captions "
                                    f'(e.g. "{ex}…" sim={s})'}
    return edges


# --------------------------------------------------------------------------- #
# C. synchronized dissemination (content-gated)
# --------------------------------------------------------------------------- #
def detect_sync_dissemination(posts, cfg, post_to_cluster, per_post_narr,
                              dup_pairs, cand):
    """Count synchronized events ONLY when the two posts share content: same
    media cluster, same narrative, or near-identical text — never time alone."""
    window = cfg.sync_window_seconds
    events = defaultdict(set)   # pair -> set of event keys (dedup)
    waves = defaultdict(set)    # pair -> set of wave buckets (window index)

    def add_event(pa, pb, why):
        if pa.account_id == pb.account_id:
            return
        dt = abs((pa.timestamp - pb.timestamp).total_seconds())
        if dt > window:
            return
        key = tuple(sorted((pa.account_id, pb.account_id)))
        ev = tuple(sorted((pa.post_id, pb.post_id)))
        events[key].add((ev, why))
        bucket = int(min(pa.timestamp, pb.timestamp).timestamp() // window)
        waves[key].add(bucket)

    # (i) shared media cluster
    cluster_posts = defaultdict(list)
    for p in posts:
        cid = post_to_cluster.get(p.post_id)
        if cid is not None:
            cluster_posts[cid].append(p)
    for cid, plist in cluster_posts.items():
        plist.sort(key=lambda p: p.timestamp)
        for a, b in combinations(plist, 2):
            if (b.timestamp - a.timestamp).total_seconds() > window:
                continue
            add_event(a, b, "media")

    # (ii) near-duplicate text pairs
    # NOTE: sharing a *narrative cluster* is deliberately NOT counted here. A
    # narrative is a loose semantic bucket; on a broad topic query it can hold
    # hundreds of unrelated posts, so "same narrative within 30 min" fires
    # constantly and manufactures coordination where there is none. A
    # synchronized event is counted only on hard shared content: the same media
    # cluster or near-identical text. (Same narrative still corroborates a group
    # that already has such a signal, via the narrative detector itself.)
    for (i, j) in dup_pairs:
        add_event(cand[i], cand[j], "text")

    edges = {}
    for key, evset in events.items():
        if len(evset) >= cfg.min_sync_events:
            whys = sorted({w for _, w in evset})
            edges[key] = {
                "weight": cfg.detector_weights["sync_dissemination"],
                "detail": f"{len(evset)} synchronized incident posts within "
                          f"{window // 60} min across {len(waves[key])} wave(s) "
                          f"(shared: {', '.join(whys)})"}
    return edges


# --------------------------------------------------------------------------- #
# D. cross-platform propagation
# --------------------------------------------------------------------------- #
def detect_cross_platform(posts, media_clusters, cfg, dup_pairs, cand):
    acct_plat = {p.account_id: p.platform for p in posts}
    edges = {}
    # via shared media across platforms
    post_acct = {p.post_id: p.account_id for p in posts}
    for c in media_clusters:
        if len(c.platforms) < 2:
            continue
        accts = sorted({post_acct[pid] for pid in c.post_ids if pid in post_acct})
        for a, b in combinations(accts, 2):
            if acct_plat.get(a) != acct_plat.get(b):
                edges[tuple(sorted((a, b)))] = {
                    "weight": cfg.detector_weights["cross_platform"],
                    "detail": f"same media appeared on {' & '.join(c.platforms)} "
                              f"(cluster #{c.cluster_id})"}
    # via near-dup captions across platforms
    for (i, j) in dup_pairs:
        a, b = cand[i], cand[j]
        if a.platform != b.platform:
            edges.setdefault(tuple(sorted((a.account_id, b.account_id))), {
                "weight": cfg.detector_weights["cross_platform"],
                "detail": f"near-identical caption on {a.platform} & {b.platform}"})
    return edges


# --------------------------------------------------------------------------- #
# E. account similarity (SUPPORTING ONLY)
# --------------------------------------------------------------------------- #
def detect_account_similarity(accounts, posts, cfg):
    edges = defaultdict(lambda: {"weight": 0.0, "detail": []})
    present = {p.account_id for p in posts}
    accs = {aid: a for aid, a in accounts.items() if aid in present}

    def add(a, b, why):
        key = tuple(sorted((a, b)))
        edges[key]["weight"] = cfg.detector_weights["account_similarity"]
        if why not in edges[key]["detail"]:
            edges[key]["detail"].append(why)

    # creation burst
    dated = sorted(((aid, a.created_at) for aid, a in accs.items() if a.created_at),
                   key=lambda t: t[1])
    window = cfg.creation_window_hours * 3600
    cur = []
    clusters = []
    for aid, ts in dated:
        if cur and (ts - cur[0][1]).total_seconds() <= window:
            cur.append((aid, ts))
        else:
            if len(cur) >= cfg.min_creation_cluster:
                clusters.append(cur)
            cur = [(aid, ts)]
    if len(cur) >= cfg.min_creation_cluster:
        clusters.append(cur)
    for cl in clusters:
        span = (cl[-1][1] - cl[0][1]).total_seconds() / 3600.0
        ids = [a for a, _ in cl]
        for a, b in combinations(ids, 2):
            add(a, b, f"accounts created within {span:.1f}h")

    # avatar reuse
    items = [(aid, a.profile_photo_phash) for aid, a in accs.items()
             if a.profile_photo_phash]
    for (a, ha), (b, hb) in combinations(items, 2):
        if hamming(ha, hb) <= cfg.avatar_phash_threshold:
            add(a, b, "reused profile photo")

    # similar handles
    handled = [(aid, a.handle) for aid, a in accs.items() if a.handle]
    for (a, ha), (b, hb) in combinations(handled, 2):
        if a != b and str_similarity(ha, hb) >= cfg.username_sim_threshold:
            add(a, b, f'similar handles ("{ha}"~"{hb}")')

    # shared external links / domains
    link_acc = defaultdict(set)
    for aid, a in accs.items():
        for u in (a.external_links or []):
            dom = entities._domain(u)
            if dom and dom not in _COMMON_DOMAINS:
                link_acc[dom].add(aid)
    for dom, s in link_acc.items():
        if 2 <= len(s) <= 15:
            for a, b in combinations(sorted(s), 2):
                add(a, b, f"shared external domain {dom}")

    return {k: {"weight": v["weight"], "detail": "; ".join(v["detail"])}
            for k, v in edges.items()}


# --------------------------------------------------------------------------- #
# F. amplification (forwards / reply chains)
# --------------------------------------------------------------------------- #
def detect_amplification(posts, cfg):
    post_author = {p.post_id: p.account_id for p in posts}
    directed = nx.DiGraph()
    for p in posts:
        src = None
        kind = None
        if p.forward_from:
            src, kind = p.forward_from, "forward"
        elif p.quote_of and p.quote_of in post_author:
            src, kind = post_author[p.quote_of], "quote"
        elif p.reply_to and p.reply_to in post_author and p.kind == "comment" \
                and not p.is_generic:
            src, kind = post_author[p.reply_to], "reply"
        if src and src != p.account_id:
            if directed.has_edge(p.account_id, src):
                directed[p.account_id][src]["weight"] += 1
            else:
                directed.add_edge(p.account_id, src, weight=1, kind=kind)
    edges = {}
    seen = set()
    for a, b, d in directed.edges(data=True):
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        reciprocal = directed.has_edge(b, a)
        fwd = d["weight"]
        rev = directed[b][a]["weight"] if reciprocal else 0
        direct = d["kind"] in ("forward", "quote")
        if reciprocal or fwd >= 2 or (direct and fwd >= 1):
            w = cfg.detector_weights["amplification"] * (1.3 if reciprocal else 1.0)
            kind_txt = ("reciprocal amplification" if reciprocal
                        else f"repeated {d['kind']} amplification")
            edges[key] = {"weight": w,
                          "detail": f"{kind_txt} ({fwd}+{rev} refs, "
                                    f"{'direct' if direct else 'inferred'})"}
    return edges, directed


# --------------------------------------------------------------------------- #
# Fusion + classification
# --------------------------------------------------------------------------- #
def detect(posts, accounts, cfg, media_clusters=None, post_to_cluster=None,
           per_post_narr=None):
    media_clusters = media_clusters or []
    post_to_cluster = post_to_cluster or {}
    per_post_narr = per_post_narr or {}

    dup_pairs, cand = _dup_pairs(posts, cfg)

    dA, _ = detect_shared_media(posts, media_clusters, cfg)
    dB = detect_near_dup_caption(posts, cfg, dup_pairs, cand)
    dC = detect_sync_dissemination(posts, cfg, post_to_cluster, per_post_narr,
                                   dup_pairs, cand)
    dD = detect_cross_platform(posts, media_clusters, cfg, dup_pairs, cand)
    dE = detect_account_similarity(accounts, posts, cfg)
    dF, directed = detect_amplification(posts, cfg)

    named = [("shared_media", dA), ("near_dup_caption", dB),
             ("sync_dissemination", dC), ("cross_platform", dD),
             ("account_similarity", dE), ("amplification", dF)]

    G = nx.Graph()
    for name, edges in named:
        for (a, b), info in edges.items():
            if not G.has_edge(a, b):
                G.add_edge(a, b, weight=0.0, detectors=[], details=[])
            G[a][b]["weight"] += info["weight"]
            G[a][b]["detectors"].append(name)
            G[a][b]["details"].append(f"[{name}] {info['detail']}")

    # Retention: an edge must carry >=1 CONTENT detector AND reach min weight.
    # This is what makes temporal/profile coincidences insufficient on their own.
    drop = []
    for a, b, d in G.edges(data=True):
        has_content = any(x in cfg.content_detectors for x in d["detectors"])
        if not has_content or d["weight"] < cfg.min_edge_weight:
            drop.append((a, b))
    G.remove_edges_from(drop)
    G.remove_nodes_from(list(nx.isolates(G)))

    groups = []
    gid = 0
    for comp in nx.connected_components(G):
        if len(comp) < 2:
            continue
        sub = G.subgraph(comp)
        detset, details = set(), []
        for _, _, data in sub.edges(data=True):
            detset.update(data["detectors"])
            details.extend(data["details"])
        # dedup detail lines
        seen, uniq = set(), []
        for line in details:
            if line not in seen:
                seen.add(line)
                uniq.append(line)
        classification, confidence, explain = _classify(comp, detset, uniq, cfg)
        score = round(sum(data["weight"] for _, _, data in sub.edges(data=True))
                      / max(1, sub.number_of_edges()), 2)
        groups.append({
            "group_id": gid,
            "classification": classification,
            "confidence": confidence,
            "confidence_explain": explain,
            "account_ids": sorted(comp),
            "score": score,
            "detectors": sorted(detset),
            "content_detectors": sorted(detset & set(cfg.content_detectors)),
            "evidence": _evidence_summary(comp, detset, uniq, classification,
                                          confidence, explain),
            "_detail_lines": uniq[:16],
        })
        gid += 1

    order = {"strong coordination indicators": 0,
             "possible coordination indicators": 1,
             "insufficient evidence": 2}
    groups.sort(key=lambda g: (order.get(g["classification"], 9),
                               -len(g["account_ids"]), -g["score"]))
    for i, g in enumerate(groups):
        g["group_id"] = i
    return groups, G, directed


def _classify(comp, detset, detail_lines, cfg):
    content = detset & set(cfg.content_detectors)
    n_acc = len(comp)
    strong_media = ("shared_media" in detset
                    and any("exact_file" in d or "keyframes" in d
                            for d in detail_lines))
    # A group is only "strong" when accounts actually pushed the SAME media or
    # the SAME claim. Amplification (reply/forward chains) and synchronized
    # timing corroborate but are never, on their own, strong: on YouTube every
    # comment "replies to" its video, so reply-chain amplification is common and
    # not evidence of a campaign.
    strong_signal = (strong_media or "shared_media" in detset
                     or "near_dup_caption" in detset)

    # confidence scoring
    pts = 0
    if any("exact_file" in d for d in detail_lines):
        pts += 3
    elif any("keyframes" in d for d in detail_lines):
        pts += 2
    elif "shared_media" in detset:
        pts += 1
    if "near_dup_caption" in detset:
        pts += 2
    if "amplification" in detset:
        pts += 2
    if "cross_platform" in detset:
        pts += 1
    if "sync_dissemination" in detset:
        pts += 1
    if "account_similarity" in detset:
        pts += 1
    pts += max(0, len(content) - 1)        # corroboration bonus
    if n_acc >= 5:
        pts += 1

    confidence = "High" if pts >= 6 else ("Medium" if pts >= 3 else "Low")

    if (len(content) >= cfg.strong_min_signal_types and n_acc >= cfg.strong_min_accounts
            and strong_signal):
        classification = "strong coordination indicators"
    elif content:
        classification = "possible coordination indicators"
    else:
        classification = "insufficient evidence"

    explain = (f"Confidence {confidence}: {len(content)} independent content "
               f"signal(s) ({', '.join(sorted(content)) or 'none'}), "
               f"{n_acc} accounts"
               + (", exact-file media match" if any('exact_file' in d for d in detail_lines) else
                  (", matching video keyframes" if any('keyframes' in d for d in detail_lines) else ""))
               + ("" if "cross_platform" not in detset else ", cross-platform")
               + f". Score {pts}.")
    return classification, confidence, explain


def _evidence_summary(comp, detset, detail_lines, classification, confidence,
                      explain):
    head = (f"{len(comp)} accounts — {classification} ({confidence} confidence). "
            f"Signals: {', '.join(sorted(detset))}. ")
    return head + " ".join(detail_lines[:5]) + " " + explain
