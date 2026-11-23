"""
Entity extraction — hashtags, URLs, domains, @mentions — from post text.

Entities are strong, platform-agnostic signals:
  * coordination: accounts pushing the SAME link/domain is classic astroturfing
    (the shared_link detector uses this).
  * narratives: shared hashtags/domains sharpen what a cluster is about.
  * dashboard: "top links / hashtags" make a narrative legible to a human.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_HASHTAG = re.compile(r"(?<!\w)#(\w{2,50})")
_MENTION = re.compile(r"(?<!\w)@([A-Za-z0-9_\.]{2,50})")
_URL = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_TME = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{3,})", re.IGNORECASE)


def extract(text: str) -> dict:
    """Return {hashtags, mentions, urls, domains} for one post's text."""
    text = text or ""
    hashtags = sorted({h.lower() for h in _HASHTAG.findall(text)})
    mentions = sorted({m.lower().rstrip(".") for m in _MENTION.findall(text)})
    urls = [u.rstrip(".,);]") for u in _URL.findall(text)]
    # Telegram t.me links that aren't full URLs
    for ch in _TME.findall(text):
        urls.append(f"https://t.me/{ch}")
    domains = sorted({_domain(u) for u in urls if _domain(u)})
    return {
        "hashtags": hashtags,
        "mentions": mentions,
        "urls": sorted(set(urls)),
        "domains": domains,
    }


def _domain(url: str) -> str:
    try:
        host = urlparse(url if "://" in url else "http://" + url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def for_posts(posts) -> dict:
    """Return {post_id: entities} for a list of posts."""
    return {p.post_id: extract(p.text) for p in posts}
