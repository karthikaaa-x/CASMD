"""
Central configuration.

Two objects live here:

  * `Incident` — the investigation input interface (name, keywords, description,
    date range, platforms). This is what the operator supplies.
  * `Config`   — every tunable detection threshold. All of them live in one
    place so the analysis is transparent and auditable: a reviewer can see
    exactly what decision each detector makes and change it without reading code.

Only YouTube and Telegram are supported platforms. The architecture is modular
(each collector is a separate module) so another platform could be added later,
but the shipped system collects from YouTube and Telegram only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SUPPORTED_PLATFORMS = ("youtube", "telegram")


# --------------------------------------------------------------------------- #
# Investigation input
# --------------------------------------------------------------------------- #
@dataclass
class Incident:
    """The operator-supplied description of what is being investigated."""
    name: str = "Untitled incident"
    primary_keyword: str = ""
    additional_keywords: list[str] = field(default_factory=list)
    description: str = ""
    date_start: str = "2026-11-10"         # YYYY-MM-DD
    date_end: str = "2026-11-19"           # YYYY-MM-DD
    platforms: tuple = SUPPORTED_PLATFORMS

    def all_keywords(self) -> list[str]:
        kws = []
        if self.primary_keyword:
            kws.append(self.primary_keyword)
        kws.extend(self.additional_keywords or [])
        # de-dup, preserve order, drop empties
        seen, out = set(), []
        for k in kws:
            k = (k or "").strip()
            lk = k.lower()
            if k and lk not in seen:
                seen.add(lk)
                out.append(k)
        return out

    def reference_text(self) -> str:
        """The text used as the incident's semantic anchor."""
        parts = [self.name, self.primary_keyword,
                 " ".join(self.additional_keywords or []), self.description]
        return "  ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Detection thresholds
# --------------------------------------------------------------------------- #
@dataclass
class Config:
    incident: Incident = field(default_factory=Incident)

    db_path: str = "data/casmd.sqlite"
    out_dir: str = "output"

    # -- relevance engine ------------------------------------------------- #
    # Scores are in [0, 1]. A post at/above `relevant_threshold` is admitted to
    # the incident dataset; between the two thresholds it is "needs review";
    # below `review_threshold` it is irrelevant and excluded from analysis.
    relevant_threshold: float = 0.45
    review_threshold: float = 0.22
    # A YouTube comment can only be relevant if its parent video is relevant.
    require_relevant_parent: bool = True
    # Comments contribute to coordination only if they carry real incident
    # content (score >= this and not generic). Stops comment spam dominating.
    comment_min_relevance_for_coord: float = 0.45

    # -- media correlation ------------------------------------------------- #
    # pHash Hamming distance at/below which two IMAGES are "visually similar".
    media_phash_threshold: int = 10
    # Fraction of keyframe hashes that must match (within phash threshold) for
    # two videos to be judged near-identical.
    media_keyframe_overlap: float = 0.6
    # Avatars: tighter threshold (exact-ish reuse), used by account-similarity.
    avatar_phash_threshold: int = 6
    # Allow downloading media bytes in LIVE mode for hashing (off by default:
    # keeps the core pipeline cheap and avoids ToS/bandwidth surprises).
    download_media: bool = False
    enable_ocr: bool = False               # optional, needs pytesseract
    enable_transcribe: bool = False        # optional, needs faster-whisper

    # -- narrative clustering -------------------------------------------- #
    min_narrative_size: int = 3
    # cosine on TF-IDF; lower groups more loosely-worded posts into one narrative.
    # 0.08 suits short, varied social text; raise it for tighter clusters, or
    # install sentence-transformers for semantic narrative clustering.
    narrative_sim_threshold: float = 0.08

    # -- coordination: near-duplicate caption ---------------------------- #
    text_sim_threshold: float = 0.80       # cosine on char n-grams; >= = near-dup
    min_shared_dupes: int = 2              # near-dup posts needed to link a pair
    # Only treat text as a coordination-grade caption if it is substantive. Short
    # reused phrases ("love this video", "gta 6 cant wait") collide among genuine
    # fans and must not be read as a coordinated message. Real incident captions
    # are sentence-length.
    min_caption_tokens: int = 5

    # -- coordination: synchronized dissemination ------------------------ #
    # A co-posting event is only counted when BOTH posts are incident-relevant
    # AND share meaningful content (same media cluster / narrative / near-dup
    # text). Temporal proximity on its own is never counted.
    sync_window_seconds: int = 1800        # 30-minute window for a "wave"
    min_sync_events: int = 2               # synchronized events needed to link

    # -- coordination: account similarity (SUPPORTING signals only) ------ #
    creation_window_hours: int = 48
    min_creation_cluster: int = 3
    username_sim_threshold: float = 0.72   # char-sim between handles

    # -- fusion / classification ----------------------------------------- #
    # Weight each detector contributes to an account-account edge.
    detector_weights: dict = field(default_factory=lambda: {
        "shared_media":        1.3,   # same / near-identical media
        "near_dup_caption":    1.0,   # near-identical incident captions
        "sync_dissemination":  0.9,   # repeated synchronized incident posting
        "cross_platform":      0.8,   # same media/caption on YT and TG
        "amplification":       0.9,   # forwards / repeated sharing (direct)
        "account_similarity":  0.5,   # creation burst / avatar / handle (support)
    })
    # Detectors that carry real CONTENT/MEDIA evidence. An account pair must be
    # supported by at least one of these before it can appear in a group at all:
    # this is what guarantees temporal/profile coincidences are never enough.
    content_detectors: tuple = (
        "shared_media", "near_dup_caption", "sync_dissemination",
        "cross_platform", "amplification",
    )
    # Edge retention: must reach this fused weight.
    min_edge_weight: float = 0.9
    # Group classification: a group is "strong" when it has at least this many
    # independent signal types including >=1 strong media/caption signal and
    # reaches this many accounts; otherwise "possible"; else insufficient.
    strong_min_signal_types: int = 2
    strong_min_accounts: int = 3

    # convenience passthroughs ------------------------------------------- #
    @property
    def date_start(self) -> str:
        return self.incident.date_start

    @property
    def date_end(self) -> str:
        return self.incident.date_end

    @property
    def platforms(self) -> tuple:
        return self.incident.platforms
