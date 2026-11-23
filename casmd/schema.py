"""
Unified data schema for the Coordinated Activity & Disinformation Detection
System (CASMD).

Everything collected from every platform is normalized into a small set of
shapes: a `Post`, an `Account`, and `Media`. Analysis then adds derived records:
`MediaAsset` / `MediaCluster` (media correlation) and relevance / coordination
annotations that live on the Post.

Design rules
------------
  * IDs are always prefixed with the platform ("tg:", "yt:") so they are
    globally unique and never collide across platforms.
  * Timestamps are always timezone-aware UTC.
  * We always keep the original payload in `raw` so we can recompute anything
    later without re-collecting.
  * `refs` (reply_to / forward_from / quote_of) capture amplification
    relationships, which is what lets us reconstruct who is amplifying whom.
  * Relevance is first-class: every post carries an incident-relevance score,
    decision and the reason, because the central principle of this system is
    "establish the content is about the same incident BEFORE analysing
    coordination".

This module is deliberately dependency-free (stdlib only) so it imports cleanly
on locked-down analyst machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Any


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #
@dataclass
class Media:
    """A single media item attached to a post (a video, an image/thumbnail)."""
    type: str                              # "image" | "video" | "other"
    url: Optional[str] = None
    # Stable per-item id (assigned by the media engine). Lets posts reference a
    # shared MediaAsset / MediaCluster.
    media_id: Optional[str] = None
    # Exact-file hash (hex). Only set when the bytes were actually available.
    sha256: Optional[str] = None
    # Perceptual hash (hex) of the image / thumbnail (dHash). Catches resized or
    # lightly edited *images*. None for video unless a representative frame hash.
    phash: Optional[str] = None
    # Perceptual hashes of representative video keyframes (list of hex strings),
    # populated only when the video could be downloaded + sampled with FFmpeg.
    keyframe_hashes: list[str] = field(default_factory=list)
    # Text pulled off the image with OCR, where available (optional module).
    ocr_text: Optional[str] = None
    # Speech-to-text transcript of the video's audio, where available (optional).
    transcript: Optional[str] = None
    # Local path to the downloaded bytes, where permitted/available.
    local_path: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Account / channel
# --------------------------------------------------------------------------- #
@dataclass
class Account:
    account_id: str                        # e.g. "tg:12345" / "yt:UC..."
    platform: str                          # "telegram" | "youtube"
    handle: Optional[str] = None
    display_name: Optional[str] = None
    kind: str = "user"                     # "channel" | "user"
    description: Optional[str] = None      # channel/profile description text
    # Account/channel creation time (UTC). Often unavailable; None where unknown.
    created_at: Optional[datetime] = None
    # Perceptual hash of the profile photo (hex), for avatar reuse.
    profile_photo_phash: Optional[str] = None
    profile_photo_url: Optional[str] = None
    # External links in the bio/description (normalised), for shared-link signals.
    external_links: list[str] = field(default_factory=list)
    followers: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "handle": self.handle,
            "display_name": self.display_name,
            "kind": self.kind,
            "description": self.description,
            "created_at": _dt_to_iso(self.created_at),
            "profile_photo_phash": self.profile_photo_phash,
            "profile_photo_url": self.profile_photo_url,
            "external_links": _json(self.external_links),
            "followers": self.followers,
            "raw": _json(self.raw),
        }


# --------------------------------------------------------------------------- #
# Post / message / comment
# --------------------------------------------------------------------------- #
@dataclass
class Post:
    post_id: str                           # e.g. "yt:Xq3abc"
    platform: str
    account_id: str
    timestamp: datetime                    # UTC, timezone-aware
    # kind distinguishes an original upload from a comment/reply from a channel
    # message. This matters a lot: a comment must never be treated like an
    # upload, and large volumes of generic comments must not dominate analysis.
    kind: str = "post"                     # "video" | "comment" | "message" | "post"
    text: str = ""
    lang: Optional[str] = None
    media: list[Media] = field(default_factory=list)
    # Engagement is a point-in-time snapshot at collection.
    likes: int = 0
    shares: int = 0                        # forwards / shares
    replies: int = 0
    views: int = 0
    url: Optional[str] = None
    # Amplification references.
    reply_to: Optional[str] = None         # post_id being replied to / parent video
    forward_from: Optional[str] = None     # account_id the post was forwarded from
    quote_of: Optional[str] = None         # post_id being quoted
    parent_id: Optional[str] = None        # parent *video* post_id for a comment

    # ---- relevance annotations (filled by the relevance engine) ---------- #
    relevance_score: float = 0.0
    relevance_decision: str = "unscored"   # relevant | review | irrelevant
    relevance_reason: str = ""
    relevance_signals: dict[str, Any] = field(default_factory=dict)
    is_generic: bool = False               # low-information text (e.g. "first")

    raw: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict:
        return {
            "post_id": self.post_id,
            "platform": self.platform,
            "account_id": self.account_id,
            "timestamp": _dt_to_iso(self.timestamp),
            "kind": self.kind,
            "text": self.text,
            "lang": self.lang,
            "media": _json([m.to_dict() for m in self.media]),
            "likes": self.likes,
            "shares": self.shares,
            "replies": self.replies,
            "views": self.views,
            "url": self.url,
            "reply_to": self.reply_to,
            "forward_from": self.forward_from,
            "quote_of": self.quote_of,
            "parent_id": self.parent_id,
            "relevance_score": self.relevance_score,
            "relevance_decision": self.relevance_decision,
            "relevance_reason": self.relevance_reason,
            "relevance_signals": _json(self.relevance_signals),
            "is_generic": 1 if self.is_generic else 0,
            "raw": _json(self.raw),
        }


# --------------------------------------------------------------------------- #
# Media correlation records (derived; produced by analysis/media.py)
# --------------------------------------------------------------------------- #
@dataclass
class MediaAsset:
    """One concrete media item observed on one post."""
    asset_id: str
    post_id: str
    account_id: str
    platform: str
    type: str
    timestamp: datetime
    url: Optional[str] = None
    sha256: Optional[str] = None
    phash: Optional[str] = None
    keyframe_hashes: list[str] = field(default_factory=list)
    ocr_text: Optional[str] = None
    transcript: Optional[str] = None


@dataclass
class MediaCluster:
    """A set of media assets judged to be the same or near-identical content."""
    cluster_id: int
    asset_ids: list[str]
    post_ids: list[str]
    account_ids: list[str]
    platforms: list[str]
    first_observed: datetime
    match_types: list[str]                 # e.g. ["exact_file", "keyframes"]
    confidence: str                        # high | medium | low
    sha256: Optional[str] = None
    phash: Optional[str] = None
    evidence: str = ""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
import json as _json_mod


def _json(obj) -> str:
    return _json_mod.dumps(obj, ensure_ascii=False, default=str)


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s)
