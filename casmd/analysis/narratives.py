"""
Narrative detection = grouping incident-relevant posts by the claim they make.

Different posts about one incident can carry very different narratives that may
share the same media. Example (ship-bombing video):
    A) an Iranian naval vessel was bombed
    B) a commercial cargo ship was attacked
    C) the footage is from an old military exercise
    D) the footage is AI-generated
    E) the footage is unrelated to the current conflict

Pipeline:
  1. Operate ONLY on incident-relevant, non-generic posts (the caller filters;
     this is what keeps generic comments and off-incident noise out of the
     narrative map).
  2. Cluster post texts by TF-IDF cosine similarity (deterministic, no model
     download). The production path can swap in sentence embeddings via
     `semantic_embed` without touching callers.
  3. For each cluster, derive a STANCE toward the incident claim
     (asserting / questioning / debunking) and a claim-type LABEL
     (Unverified claim / Potential misinformation / Contradictory claim /
      Debunking content / Verified information).
  4. Attach the media clusters that appear in the narrative's posts.

Nothing is labelled "misinformation" merely for being suspicious or widely
shared; labels reflect the language of the posts and (for "Verified
information") the presence of reputable-source citations.
"""

from __future__ import annotations

import re
from collections import defaultdict, Counter

import numpy as np

from . import textvec, entities


# --------------------------------------------------------------------------- #
# Stance lexicons
# --------------------------------------------------------------------------- #
_DEBUNK = re.compile(
    r"\b(fake|hoax|false|debunk\w*|fact[\s-]?check\w*|old footage|old video|"
    r"years? ago|recycled|reused|ai[\s-]?generated|ai generated|deepfake|cgi|"
    r"manipulat\w+|doctored|staged|not real|misleading|unrelated|"
    r"from \d{4}|simulation|simulated|edited|out of context)\b", re.I)
_QUESTION = re.compile(
    r"(\?|\bis this (real|true|fake)|\breal\?|\bsource\b|anyone know|"
    r"can anyone confirm|unverified|is it true|not sure if)", re.I)
_SENSATIONAL = re.compile(
    r"\b(breaking|urgent|shock\w*|exposed|they (are )?hiding|wake up|"
    r"share (this|now)|must see|before (it|they)|cover[\s-]?up)\b", re.I)

_NEWS_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "aljazeera.com",
    "theguardian.com", "nytimes.com", "cnn.com", "ndtv.com", "thehindu.com",
    "timesofindia.indiatimes.com", "france24.com", "dw.com",
}


def post_stance(text: str) -> str:
    t = text or ""
    if _DEBUNK.search(t):
        return "debunking"
    if _QUESTION.search(t):
        return "questioning"
    return "asserting"


# --------------------------------------------------------------------------- #
def semantic_embed(texts):
    """Dense multilingual embeddings via sentence-transformers if installed,
    else None (TF-IDF fallback is used)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return np.asarray(model.encode(texts, normalize_embeddings=True),
                      dtype=np.float32)


def detect(posts, cfg, post_to_cluster=None):
    """`posts` must already be the incident-relevant, non-generic posts.
    Returns (narratives, assignments, per_post)."""
    post_to_cluster = post_to_cluster or {}
    if not posts:
        return [], [], {}

    texts = [p.text for p in posts]
    Xd, features = textvec.tfidf(texts, analyzer="word", min_df=1)
    sem = semantic_embed(texts)
    Xcluster = sem if sem is not None else Xd
    labels = textvec.cluster_threshold(Xcluster, cfg.narrative_sim_threshold)

    groups = defaultdict(list)
    for idx, lab in enumerate(labels):
        groups[lab].append(idx)

    terms = np.array(features)
    narratives, assignments, per_post = [], [], {}
    next_id = 0
    for lab, idxs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(idxs) < cfg.min_narrative_size:
            for i in idxs:
                per_post[posts[i].post_id] = -1
                assignments.append((posts[i].post_id, -1))
            continue
        sub = Xd[idxs]
        mean = sub.mean(axis=0)
        top = terms[np.argsort(mean)[::-1][:8]].tolist()

        plist = [posts[i] for i in idxs]
        stances = Counter(post_stance(p.text) for p in plist)
        sens = sum(1 for p in plist if _SENSATIONAL.search(p.text or ""))
        news = _news_share(plist)
        stance, label = _label(stances, sens / len(plist), news)

        media_clusters = sorted({post_to_cluster[p.post_id] for p in plist
                                 if p.post_id in post_to_cluster})

        narratives.append({
            "narrative_id": next_id,
            "label": label,
            "stance": stance,
            "claim_summary": _summary(plist),
            "keywords": top,
            "size": len(idxs),
            "unique_accounts": len({p.account_id for p in plist}),
            "stance_breakdown": dict(stances),
            "media_cluster_ids": media_clusters,
        })
        for i in idxs:
            per_post[posts[i].post_id] = next_id
            assignments.append((posts[i].post_id, next_id))
        next_id += 1

    return narratives, assignments, per_post


def _news_share(plist) -> float:
    cited = 0
    for p in plist:
        doms = entities.extract(p.text)["domains"]
        if any(d in _NEWS_DOMAINS for d in doms):
            cited += 1
    return cited / max(1, len(plist))


def _label(stances, sensational_frac, news_share):
    dominant = stances.most_common(1)[0][0] if stances else "asserting"
    if dominant == "debunking":
        return "debunking", "Debunking content"
    if dominant == "questioning":
        return "questioning", "Unverified claim"
    # asserting
    if news_share >= 0.4:
        return "reporting", "Verified information"
    if sensational_frac >= 0.3:
        return "asserting", "Potential misinformation"
    # Plain assertions with no sensational / debunk / news markers are ordinary
    # topical discussion — not a claim to flag. Calling everything an "unverified
    # claim" is misleading on broad topic queries.
    return "discussion", "General discussion"


def _summary(plist):
    """Short readable summary = cleaned text of the most-engaged example."""
    ranked = sorted(plist, key=lambda p: -(p.likes + p.shares + p.views))
    src = ranked[0].text if ranked else ""
    t = re.sub(r"https?://\S+", "", re.sub(r"\s+", " ", src or "")).strip()
    return (t[:140].rsplit(" ", 1)[0] + "…") if len(t) > 140 else (t or "(no text)")


# --------------------------------------------------------------------------- #
# Volume aggregations for the dashboard.
# --------------------------------------------------------------------------- #
def volume_over_time(posts, per_post_narr):
    out = defaultdict(lambda: defaultdict(int))
    for p in posts:
        nid = per_post_narr.get(p.post_id, -1)
        if nid == -1:
            continue
        out[nid][p.timestamp.date().isoformat()] += 1
    return {k: dict(v) for k, v in out.items()}


def volume_per_platform(posts, per_post_narr):
    out = defaultdict(lambda: defaultdict(int))
    for p in posts:
        nid = per_post_narr.get(p.post_id, -1)
        if nid == -1:
            continue
        out[nid][p.platform] += 1
    return {k: dict(v) for k, v in out.items()}
