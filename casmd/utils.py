"""Small shared utilities: hashing, Hamming distance, text normalization,
string similarity."""

from __future__ import annotations

import re
import hashlib
from difflib import SequenceMatcher

import numpy as np

try:
    from PIL import Image          # optional: only needed for real image hashing
    _HAVE_PIL = True
except Exception:                  # Pillow has compiled DLLs; may be policy-blocked
    _HAVE_PIL = False


# --------------------------------------------------------------------------- #
# Perceptual hashing (dHash) — real implementation, not faked.
#
# dHash is robust to resizing / minor edits: it compares adjacent pixel
# brightness. Two visually identical images produce hashes a few bits apart;
# unrelated images differ in roughly half their bits.
# --------------------------------------------------------------------------- #
def dhash(image_path: str, hash_size: int = 8) -> str:
    if not _HAVE_PIL:
        raise RuntimeError("Pillow unavailable (needed only for image hashing)")
    img = Image.open(image_path).convert("L").resize(
        (hash_size + 1, hash_size), Image.LANCZOS)
    px = np.asarray(img, dtype=np.int16)
    diff = px[:, 1:] > px[:, :-1]
    value = 0
    for b in diff.flatten():
        value = (value << 1) | int(b)
    return f"{value:0{hash_size * hash_size // 4}x}"


def hamming(h1: str, h2: str) -> int:
    """Hamming distance between two hex hash strings."""
    if not h1 or not h2:
        return 999
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except ValueError:
        return 999


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(text: str, n: int = 8) -> str:
    """Deterministic short hex id from a string (identical strings collide)."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=n).hexdigest()


# --------------------------------------------------------------------------- #
# Text normalization + similarity for near-duplicate detection.
# --------------------------------------------------------------------------- #
_URL = re.compile(r"https?://\S+")
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    t = (text or "").lower()
    t = _URL.sub(" ", t)
    t = re.sub(r"[^\w#@\s]", " ", t)
    t = _WS.sub(" ", t).strip()
    return t


def str_similarity(a: str, b: str) -> float:
    """Character-level similarity in [0,1] (used for handles / short strings)."""
    a, b = (a or "").lower(), (b or "").lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
