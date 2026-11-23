"""
Incident relevance engine — the most important new component.

Central principle of the whole system: before a post or comment can take part in
narrative or coordination analysis, it must be established as being about the
*same incident*. This module decides that.

For every post it computes a relevance score in [0, 1] from several transparent
signals and assigns one of three decisions:

    relevant   (score >= cfg.relevant_threshold)   -> admitted to the dataset
    review     (cfg.review_threshold <= score < relevant_threshold)
    irrelevant (score < cfg.review_threshold)       -> excluded from analysis

Signals
-------
  primary_kw   : the incident's primary keyword phrase appears in the text
  related_kw   : how many additional/related keywords appear
  semantic     : TF-IDF cosine similarity of the text to the incident reference
                 (name + keywords + description)
  entity       : overlap of salient incident entity tokens with the text
  media_match  : the post carries media that belongs to an incident media
                 cluster (applied in a second pass, can promote a borderline
                 post) — optional
  parent       : for YouTube COMMENTS, the parent video must itself be relevant,
                 otherwise the comment is excluded regardless of its own text.
                 This is what keeps unrelated comments (e.g. "GTA 6 is amazing"
                 under a gaming video) out of the incident dataset.

Generic, low-information text ("first", "nice video", "wow") is detected and
flagged (`is_generic`). Generic text can never, on its own, make a post relevant,
and such posts are excluded from the content-based coordination detectors.

Everything is deterministic (no randomness, no network) so repeated runs on the
same data give identical results.
"""

from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from . import textvec
from ..utils import normalize_text


# --------------------------------------------------------------------------- #
# Generic / low-information text detection
# --------------------------------------------------------------------------- #
_GENERIC_PHRASES = {
    "first", "first comment", "firstt", "second", "early", "nice", "nice video",
    "nice one", "great video", "good video", "wow", "amazing", "awesome", "cool",
    "lol", "lmao", "haha", "best", "love it", "love this", "like", "subscribe",
    "like and subscribe", "who is here", "who else is here", "anyone here",
    "hi", "hello", "yo", "ok", "okay", "thanks", "thank you", "good",
    "best youtubers ever", "best youtuber", "gg", "w", "fire", "goat",
}
# Topics that are common off-incident noise in comment sections.
_NOISE_TOKENS = {"gta", "gta6", "minecraft", "fortnite", "roblox", "giveaway",
                 "subscribe", "subscriber", "subscribers", "pewdiepie"}

_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def is_generic_text(text: str, incident_tokens: set[str]) -> bool:
    """A post is generic if it is a stock phrase / emoji-only / very short and
    carries no incident-specific token."""
    raw = (text or "").strip()
    norm = normalize_text(raw)
    toks = norm.split()
    # Strip emoji to judge length of real words.
    stripped = _EMOJI.sub("", raw).strip()
    has_incident_tok = any(t in incident_tokens for t in toks)
    if has_incident_tok:
        return False
    if not stripped or not toks:
        return True
    if norm in _GENERIC_PHRASES:
        return True
    if len(toks) <= 3 and (norm in _GENERIC_PHRASES or len(stripped) <= 12):
        return True
    if any(t in _NOISE_TOKENS for t in toks) and len(toks) <= 8:
        return True
    # Mostly non-incident single-sentiment-word comments.
    if len(toks) <= 2:
        return True
    return False


# --------------------------------------------------------------------------- #
# Keyword / token helpers
# --------------------------------------------------------------------------- #
_STOP = set("""a an the of to in on for and or with is are was were be been this
that it its as at by from into about over under after before during up down out
you your we they he she his her our their i me my""".split())


def _salient_tokens(phrases: list[str]) -> set[str]:
    out = set()
    for ph in phrases:
        for t in normalize_text(ph).split():
            if len(t) >= 3 and t not in _STOP:
                out.add(t)
    return out


def _phrase_present(norm_text: str, phrase: str) -> bool:
    """True if all salient tokens of `phrase` appear in the text (order-free),
    which tolerates minor word-order and punctuation differences."""
    toks = [t for t in normalize_text(phrase).split() if t not in _STOP]
    if not toks:
        return False
    if len(toks) == 1:
        return re.search(rf"\b{re.escape(toks[0])}\b", norm_text) is not None
    return all(re.search(rf"\b{re.escape(t)}\b", norm_text) for t in toks)


def quick_relevance(incident, text: str, tags=None) -> float:
    """Lightweight corpus-free relevance score in [0,1], used by collectors to
    decide (for example) whether a video is on-topic enough to pull its comments.
    The full `score_posts` pass re-scores everything consistently afterwards."""
    hay = normalize_text((text or "") + " " + " ".join(tags or []))
    if not hay:
        return 0.0
    primary = 1.0 if (incident.primary_keyword and
                      _phrase_present(hay, incident.primary_keyword)) else 0.0
    rel = incident.additional_keywords or []
    related_hit = 1.0 if any(_phrase_present(hay, k) for k in rel) else 0.0
    kw = max(primary, 0.8 * related_hit)
    ent_tokens = _salient_tokens(incident.all_keywords())
    ent_hit = sum(1 for t in ent_tokens if re.search(rf"\b{re.escape(t)}\b", hay))
    entity = min(1.0, ent_hit / max(1, min(4, len(ent_tokens)))) if ent_tokens else 0.0
    return min(1.0, 0.70 * kw + 0.30 * entity)


# --------------------------------------------------------------------------- #
# Full relevance pass
# --------------------------------------------------------------------------- #
def score_posts(incident, cfg, posts) -> dict:
    """Score every post, handle comment parent-gating, set relevance fields in
    place, and return summary stats. Deterministic."""
    incident_tokens = _salient_tokens(incident.all_keywords())
    ref = incident.reference_text()

    # Semantic similarity via TF-IDF (reference doc first, then every post).
    texts = [ref] + [p.text for p in posts]
    X, _ = textvec.tfidf(texts, analyzer="word", ngram_range=(1, 2), min_df=1)
    ref_vec = X[0]
    sem = (X[1:] @ ref_vec) if X.shape[0] > 1 else np.zeros(len(posts))

    # First pass: own-text score for every post.
    own = {}
    for i, p in enumerate(posts):
        hay = normalize_text(p.text)
        primary = 1.0 if (incident.primary_keyword and
                          _phrase_present(hay, incident.primary_keyword)) else 0.0
        rel = incident.additional_keywords or []
        hits = [k for k in rel if _phrase_present(hay, k)]
        related_hit = 1.0 if hits else 0.0
        kw = max(primary, 0.8 * related_hit)
        ent_hit = sum(1 for t in incident_tokens
                      if re.search(rf"\b{re.escape(t)}\b", hay))
        entity = (min(1.0, ent_hit / max(1, min(4, len(incident_tokens))))
                  if incident_tokens else 0.0)
        semantic = float(sem[i]) if i < len(sem) else 0.0

        generic = is_generic_text(p.text, incident_tokens)
        p.is_generic = generic

        # keyword/semantic/entity blend; weights sum to ~1 so score stays in [0,1]
        score = 0.55 * kw + 0.30 * min(1.0, semantic) + 0.15 * entity
        if generic:
            score *= 0.25     # generic text can never be relevant on its own

        signals = {
            "primary_keyword": round(primary, 3),
            "related_hit": round(related_hit, 3),
            "related_matches": hits,
            "semantic": round(semantic, 3),
            "entity": round(entity, 3),
            "generic": generic,
        }
        own[p.post_id] = (min(1.0, score), signals)

    # Assign own-text decisions to EVERY post (comments included). Comment
    # parent-gating is applied later by gate_comments(), AFTER the media engine
    # has had a chance to promote a parent video via shared-media evidence.
    for p in posts:
        score, signals = own[p.post_id]
        p.relevance_score = round(score, 4)
        p.relevance_decision = decide(cfg, score)
        p.relevance_signals = signals
        p.relevance_reason = _reason(p.relevance_decision, signals, None)

    # Stats
    counts = defaultdict(int)
    for p in posts:
        counts[p.relevance_decision] += 1
    return {
        "relevant": counts["relevant"],
        "review": counts["review"],
        "irrelevant": counts["irrelevant"],
        "total": len(posts),
        "generic": sum(1 for p in posts if p.is_generic),
    }


def decide(cfg, score):
    if score >= cfg.relevant_threshold:
        return "relevant"
    if score >= cfg.review_threshold:
        return "review"
    return "irrelevant"


def gate_comments(cfg, posts) -> dict:
    """Apply YouTube comment parent-gating AFTER media promotion. A comment can be
    relevant only if its parent video is relevant; a substantive on-topic comment
    under a relevant video gets a small bonus. Returns updated stats."""
    by_id = {p.post_id: p for p in posts}
    for p in posts:
        if p.kind != "comment":
            continue
        parent = by_id.get(p.parent_id) if p.parent_id else None
        parent_decision = parent.relevance_decision if parent else None
        p.relevance_signals["parent_decision"] = parent_decision
        if cfg.require_relevant_parent and (parent is None
                                            or parent_decision != "relevant"):
            p.relevance_decision = "irrelevant"
            p.relevance_signals["gated_by_parent"] = True
            p.relevance_reason = (
                "Excluded: parent video is not incident-relevant"
                if parent is not None else
                "Excluded: parent video missing/not collected")
            continue
        if not p.is_generic and parent_decision == "relevant":
            p.relevance_score = round(min(1.0, p.relevance_score + 0.10), 4)
        p.relevance_decision = decide(cfg, p.relevance_score)
        p.relevance_reason = _reason(p.relevance_decision, p.relevance_signals,
                                     parent_decision)
    counts = defaultdict(int)
    for p in posts:
        counts[p.relevance_decision] += 1
    return {"relevant": counts["relevant"], "review": counts["review"],
            "irrelevant": counts["irrelevant"], "total": len(posts),
            "generic": sum(1 for p in posts if p.is_generic)}


def apply_media_boost(cfg, posts, media_clusters) -> int:
    """Second-pass promotion: a post whose media belongs to a multi-account
    incident media cluster is strong evidence of incident relevance. Promote
    'review'/'irrelevant' media-bearing posts whose media is shared. Returns the
    number of posts promoted. (Never demotes.)"""
    if not media_clusters:
        return 0
    shared_posts = set()
    for c in media_clusters:
        if len(set(c.account_ids)) >= 2:   # media shared across >=2 accounts
            shared_posts.update(c.post_ids)
    promoted = 0
    for p in posts:
        if p.post_id in shared_posts and p.relevance_decision != "relevant":
            # do not rescue purely generic text, but shared media is a real signal
            p.relevance_score = max(p.relevance_score, cfg.relevant_threshold)
            p.relevance_decision = "relevant"
            p.relevance_signals["media_match"] = True
            p.relevance_reason = ("Relevant: carries media shared across multiple "
                                  "accounts in an incident media cluster")
            promoted += 1
    return promoted


def _reason(decision, signals, parent_decision):
    bits = []
    if signals.get("primary_keyword"):
        bits.append("primary keyword present")
    if signals.get("related_matches"):
        bits.append("related terms: " + ", ".join(signals["related_matches"][:4]))
    if signals.get("semantic", 0) >= 0.2:
        bits.append(f"semantic match {signals['semantic']:.2f}")
    if signals.get("generic"):
        bits.append("generic/low-information text")
    if parent_decision:
        bits.append(f"parent video: {parent_decision}")
    body = "; ".join(bits) if bits else "no incident signals found"
    return f"{decision} ({body})"
