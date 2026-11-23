"""
Media correlation & matching engine.

Goal: identify the SAME video/image being circulated across multiple YouTube
channels and Telegram channels, and group those appearances into media clusters.

Matching layers (strongest first):
  1. SHA-256 exact-file match      -> identical bytes               (confidence: high)
  2. Video keyframe comparison     -> near-identical video          (confidence: high)
     (perceptual hashes of FFmpeg-extracted keyframes; tolerant of
      re-encode / crop / resize when enough frames still match)
  3. Perceptual image/thumbnail    -> visually similar image        (confidence: medium)
     (dHash Hamming distance)

Deliberate limitation (from the brief): two videos are NEVER declared identical on
the strength of matching thumbnails alone. Thumbnail/image-only clusters are
marked medium confidence with an explicit caveat.

The engine works on whatever media fingerprints are present on the Media objects.
In the synthetic demo and in imported datasets those fingerprints are supplied
directly (clearly-synthetic data). In LIVE mode, enrichment (download + hash +
keyframes + optional OCR / transcript) is attempted only when enabled and only
when the bytes are actually available — nothing is fabricated.

Everything is deterministic.
"""

from __future__ import annotations

import os
import tempfile
import subprocess
from collections import defaultdict

from ..schema import MediaAsset, MediaCluster
from ..utils import hamming, dhash, sha256_file


# --------------------------------------------------------------------------- #
# Asset extraction
# --------------------------------------------------------------------------- #
def build_assets(posts) -> list[MediaAsset]:
    assets = []
    for p in posts:
        for k, m in enumerate(p.media):
            if m.type not in ("image", "video"):
                continue
            aid = m.media_id or f"{p.post_id}#m{k}"
            assets.append(MediaAsset(
                asset_id=aid, post_id=p.post_id, account_id=p.account_id,
                platform=p.platform, type=m.type, timestamp=p.timestamp,
                url=m.url, sha256=m.sha256, phash=m.phash,
                keyframe_hashes=list(m.keyframe_hashes or []),
                ocr_text=m.ocr_text, transcript=m.transcript))
    return assets


def _is_thumbnail(asset) -> bool:
    return (asset.type == "image"
            and (str(asset.asset_id).startswith("ytthumb")
                 or str(asset.asset_id).startswith("ytthumb:")))


# --------------------------------------------------------------------------- #
# Pairwise matching
# --------------------------------------------------------------------------- #
def _keyframe_overlap(a, b, phash_threshold) -> float:
    if not a.keyframe_hashes or not b.keyframe_hashes:
        return 0.0
    matched = 0
    for ha in a.keyframe_hashes:
        if any(hamming(ha, hb) <= phash_threshold for hb in b.keyframe_hashes):
            matched += 1
    return matched / max(len(a.keyframe_hashes), len(b.keyframe_hashes))


def _match(a, b, cfg):
    """Return (match_type, confidence) or None if the two assets don't match."""
    if a.type != b.type:
        return None
    if a.sha256 and b.sha256 and a.sha256 == b.sha256:
        return ("exact_file", "high")
    if a.type == "video":
        ov = _keyframe_overlap(a, b, cfg.media_phash_threshold)
        if ov >= cfg.media_keyframe_overlap:
            return ("keyframes", "high")
    if a.phash and b.phash and hamming(a.phash, b.phash) <= cfg.media_phash_threshold:
        if _is_thumbnail(a) or _is_thumbnail(b):
            return ("thumbnail_similar", "medium")
        return ("image_similar", "medium")
    return None


# --------------------------------------------------------------------------- #
# Clustering (union-find)
# --------------------------------------------------------------------------- #
def cluster(assets, cfg):
    """Return (clusters, post_to_cluster) where `clusters` are multi-asset
    MediaCluster records and `post_to_cluster` maps post_id -> cluster_id."""
    n = len(assets)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    edge_types = defaultdict(set)   # root -> set of match types
    for i in range(n):
        for j in range(i + 1, n):
            mt = _match(assets[i], assets[j], cfg)
            if mt:
                union(i, j)
    # collect types per final root (second pass so roots are stable)
    for i in range(n):
        for j in range(i + 1, n):
            mt = _match(assets[i], assets[j], cfg)
            if mt:
                edge_types[find(i)].add(mt[0])

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    clusters, post_to_cluster = [], {}
    cid = 0
    for root, idxs in groups.items():
        if len(idxs) < 2:
            continue
        members = [assets[i] for i in idxs]
        types = sorted(edge_types.get(root, set()))
        confidence = _cluster_confidence(types)
        posts = sorted({m.post_id for m in members})
        accounts = sorted({m.account_id for m in members})
        platforms = sorted({m.platform for m in members})
        first = min(m.timestamp for m in members)
        sha = next((m.sha256 for m in members if m.sha256), None)
        ph = next((m.phash for m in members if m.phash), None)
        clusters.append(MediaCluster(
            cluster_id=cid, asset_ids=[m.asset_id for m in members],
            post_ids=posts, account_ids=accounts, platforms=platforms,
            first_observed=first, match_types=types, confidence=confidence,
            sha256=sha, phash=ph, evidence=_cluster_evidence(
                members, types, confidence, accounts, platforms)))
        for pid in posts:
            post_to_cluster[pid] = cid
        cid += 1

    clusters.sort(key=lambda c: (-len(c.account_ids), c.first_observed))
    # renumber by prominence
    remap = {c.cluster_id: i for i, c in enumerate(clusters)}
    for c in clusters:
        new = remap[c.cluster_id]
        for pid in c.post_ids:
            post_to_cluster[pid] = new
        c.cluster_id = new
    return clusters, post_to_cluster


def _cluster_confidence(types) -> str:
    if "exact_file" in types or "keyframes" in types:
        return "high"
    if "image_similar" in types:
        return "medium"
    if "thumbnail_similar" in types:
        return "medium"
    return "low"


def _cluster_evidence(members, types, confidence, accounts, platforms) -> str:
    label = {
        "exact_file": "identical file (SHA-256 match)",
        "keyframes": "near-identical video (matching keyframes)",
        "image_similar": "visually similar image (perceptual hash)",
        "thumbnail_similar": "similar thumbnail only (NOT proof the full videos "
                             "are identical)",
    }
    how = "; ".join(label.get(t, t) for t in types)
    cross = " across YouTube and Telegram" if len(platforms) > 1 else ""
    return (f"{len(members)} media items from {len(accounts)} account(s)"
            f"{cross} matched by: {how}. Confidence: {confidence}.")


# --------------------------------------------------------------------------- #
# Optional live enrichment (best-effort; nothing fabricated)
# --------------------------------------------------------------------------- #
def video_keyframe_hashes(path: str, n: int = 6) -> list[str]:
    """Extract ~n evenly spaced keyframes with FFmpeg and perceptual-hash each.
    Returns [] if ffmpeg/Pillow unavailable or extraction fails."""
    try:
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "f_%03d.png")
            # sample n frames spread across the video
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                   "-vf", f"thumbnail,fps=1", "-frames:v", str(n), out]
            subprocess.run(cmd, check=True, timeout=120)
            frames = sorted(f for f in os.listdir(td) if f.endswith(".png"))
            return [dhash(os.path.join(td, f)) for f in frames]
    except Exception:
        return []


def enrich_asset_from_file(asset, cfg):
    """Compute sha256 / phash / keyframes / (optional) OCR from a local file."""
    path = getattr(asset, "local_path", None)
    if not path or not os.path.isfile(path):
        return
    try:
        asset.sha256 = asset.sha256 or sha256_file(path)
    except Exception:
        pass
    if asset.type == "image":
        try:
            asset.phash = asset.phash or dhash(path)
        except Exception:
            pass
        if cfg.enable_ocr:
            asset.ocr_text = _ocr(path)
    elif asset.type == "video":
        if not asset.keyframe_hashes:
            asset.keyframe_hashes = video_keyframe_hashes(path)
        if cfg.enable_transcribe:
            asset.transcript = _transcribe(path)


def _ocr(path):
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(path))[:2000]
    except Exception:
        return None


def _transcribe(path):
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path)
        return " ".join(s.text for s in segments)[:4000]
    except Exception:
        return None
