"""
Generic dataset importer — the path to run the module LIVE on inputs someone
hands you during a demo, with no API credentials.

It reads a CSV or JSON file of posts, maps flexible column names onto the
unified schema, and writes to the same SQLite DB every analysis step reads. So
the demo flow is:

    python -m casmd.collectors.import_data --file their_data.csv --platform x
    python -m casmd.run --analyze-only

Accepted columns (first match wins; everything is optional except text + some
form of author + timestamp):

    post_id      : post_id | id | tweet_id | message_id
    platform     : platform | source            (else --platform default)
    account      : account_id | author | user | username | channel | handle
    timestamp    : timestamp | date | created_at | time | published_at
    text         : text | content | message | body | title
    likes        : likes | like_count | favorites
    shares       : shares | retweets | retweet_count | forwards
    replies      : replies | reply_count | comments | comment_count
    views        : views | view_count | impressions
    url          : url | link | permalink
    lang         : lang | language
    reply_to     : reply_to | in_reply_to | parent_id
    forward_from : forward_from | forwarded_from
    quote_of     : quote_of | quoted_id | retweet_of
    media        : media | image | image_url | video | video_url
    created_at   : account_created_at | author_created_at   (account age signal)
    avatar       : avatar | profile_photo | profile_image | avatar_url

Timestamps may be ISO-8601, 'YYYY-MM-DD HH:MM:SS', a date, or epoch seconds/ms.

Avatar handling (so the avatar-reuse detector works on real data):
  * a readable local image path   -> real perceptual hash (dHash)
  * a 16-hex string               -> used directly as a pHash
  * anything else (e.g. a URL)    -> hashed to a stable id, so IDENTICAL avatar
                                     URLs/CDN ids are detected as reuse (distance 0)
"""

from __future__ import annotations

import os
import csv
import json
import argparse
import hashlib
from datetime import datetime, timezone

from ..schema import Post, Account, Media
from ..store import Store
from ..utils import dhash, stable_id


ALIASES = {
    "post_id":   ["post_id", "id", "tweet_id", "message_id", "status_id"],
    "platform":  ["platform", "source", "network"],
    "account":   ["account_id", "author", "user", "username", "channel",
                  "handle", "author_id", "user_id", "screen_name"],
    "timestamp": ["timestamp", "date", "created_at", "time", "published_at",
                  "datetime", "created"],
    "text":      ["text", "content", "message", "body", "title", "caption",
                  "tweet", "post"],
    "likes":     ["likes", "like_count", "favorites", "favorite_count"],
    "shares":    ["shares", "retweets", "retweet_count", "forwards",
                  "share_count", "reposts"],
    "replies":   ["replies", "reply_count", "comments", "comment_count"],
    "views":     ["views", "view_count", "impressions"],
    "url":       ["url", "link", "permalink", "post_url"],
    "lang":      ["lang", "language"],
    "reply_to":  ["reply_to", "in_reply_to", "parent_id", "in_reply_to_id"],
    "forward_from": ["forward_from", "forwarded_from", "fwd_from"],
    "quote_of":  ["quote_of", "quoted_id", "retweet_of", "quoted_status_id"],
    "media":     ["media", "image", "image_url", "video", "video_url", "photo"],
    "acct_created": ["account_created_at", "author_created_at",
                     "user_created_at", "account_age"],
    "avatar":    ["avatar", "profile_photo", "profile_image", "avatar_url",
                  "profile_image_url"],
    "kind":      ["kind", "type", "post_type"],
    "parent_id": ["parent_id", "video_id", "parent"],
    "sha256":    ["sha256", "file_hash", "media_sha256"],
    "phash":     ["phash", "perceptual_hash", "media_phash"],
}


def _pick(row_lower: dict, key: str):
    for alias in ALIASES[key]:
        if alias in row_lower and row_lower[alias] not in (None, ""):
            return row_lower[alias]
    return None


def parse_dt(value) -> datetime:
    if value is None or value == "":
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        # Unix epoch. Guard against out-of-range values (e.g. a 13-digit ms
        # value right at the seconds/ms seam, or absurd numbers) so a bad feed
        # can never crash the importer — fall back to "now" like other bad dates.
        try:
            v = float(value)
            if v > 1e12:          # looks like milliseconds
                v /= 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return datetime.now(timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M",
                "%a %b %d %H:%M:%S %z %Y"):
        try:
            dt = (datetime.fromisoformat(s) if fmt is None
                  else datetime.strptime(str(value).strip(), fmt))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return datetime.now(timezone.utc)


def _avatar_phash(value) -> str | None:
    if not value:
        return None
    s = str(value)
    if os.path.isfile(s):
        try:
            return dhash(s)
        except Exception:
            pass
    if len(s) == 16 and all(c in "0123456789abcdef" for c in s.lower()):
        return s.lower()
    # Stable 64-bit id from the string: identical avatar URLs -> identical hash.
    return hashlib.blake2b(s.encode(), digest_size=8).hexdigest()


def _rows_from_file(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("data", "posts", "results", "items", "statuses"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise SystemExit("JSON must be a list of posts or {data:[...]}")
        yield from data
    else:  # csv / tsv
        delim = "\t" if ext in (".tsv", ".tab") else ","
        with open(path, newline="", encoding="utf-8") as f:
            yield from csv.DictReader(f, delimiter=delim)


PLATFORM_PREFIX = {"youtube": "yt", "telegram": "tg"}


def _prefix(platform: str) -> str:
    return PLATFORM_PREFIX.get(platform, platform[:2])


def load(path: str, store: Store, default_platform: str = "unknown") -> int:
    count = 0
    seen_accounts: dict[str, Account] = {}
    for i, raw in enumerate(_rows_from_file(path)):
        row = {str(k).strip().lower(): v for k, v in raw.items()}
        text = _pick(row, "text") or ""
        account = _pick(row, "account") or f"{default_platform}:anon{i}"
        platform = (_pick(row, "platform") or default_platform).lower()
        pre = _prefix(platform)
        if not str(account).startswith(f"{pre}:"):
            account_id = f"{pre}:{account}"
        else:
            account_id = str(account)

        pid = _pick(row, "post_id") or f"{pre}:imp:{i}"
        if not str(pid).startswith(f"{pre}:"):
            pid = f"{pre}:{pid}"

        kind = (_pick(row, "kind") or "").lower() or (
            "video" if platform == "youtube" and not _pick(row, "parent_id")
            else ("comment" if platform == "youtube" else "message"))

        media = []
        mval = _pick(row, "media")
        if mval:
            # A row that carries a video fingerprint (sha/keyframes) or whose
            # kind is a video is a video, even on Telegram where the URL gives
            # no hint.
            sha = _pick(row, "sha256")
            is_video = (kind in ("video", "message") and sha) or any(
                k in str(mval).lower() for k in ("video", ".mp4", "youtu"))
            mtype = "video" if is_video else "image"
            media.append(Media(
                mtype, url=str(mval), media_id=stable_id(str(mval), 12),
                sha256=sha,
                phash=(_pick(row, "phash") or
                       (_avatar_phash(mval) if mtype == "image" else None))))

        parent = _fqid(_pick(row, "parent_id"), platform)

        store.upsert_post(Post(
            post_id=str(pid), platform=platform, account_id=account_id,
            kind=kind,
            timestamp=parse_dt(_pick(row, "timestamp")),
            text=str(text), lang=_pick(row, "lang"), media=media,
            likes=_int(_pick(row, "likes")), shares=_int(_pick(row, "shares")),
            replies=_int(_pick(row, "replies")), views=_int(_pick(row, "views")),
            url=_pick(row, "url"),
            reply_to=_fqid(_pick(row, "reply_to"), platform),
            forward_from=_fqid(_pick(row, "forward_from"), platform),
            quote_of=_fqid(_pick(row, "quote_of"), platform),
            parent_id=parent,
            raw={"import_row": i},
        ))

        # account (keep earliest creation / first avatar seen)
        if account_id not in seen_accounts:
            seen_accounts[account_id] = Account(
                account_id=account_id, platform=platform,
                handle=str(account),
                display_name=str(account),
                created_at=parse_dt(_pick(row, "acct_created"))
                           if _pick(row, "acct_created") else None,
                profile_photo_phash=_avatar_phash(_pick(row, "avatar")),
            )
        count += 1

    for acc in seen_accounts.values():
        store.upsert_account(acc)
    store.commit()
    print(f"[import] loaded {count} posts, {len(seen_accounts)} accounts from {path}")
    return count


def _int(v) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return 0


def _fqid(v, platform):
    if not v:
        return None
    s = str(v)
    pre = _prefix(platform)
    # already fully-qualified with any known platform prefix?
    for p in list(PLATFORM_PREFIX.values()):
        if s.startswith(f"{p}:"):
            return s
    return f"{pre}:{s}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="CSV / TSV / JSON of posts")
    ap.add_argument("--platform", default="unknown",
                    help="default platform if rows don't name one")
    ap.add_argument("--db", default="data/casmd.sqlite")
    ap.add_argument("--fresh", action="store_true", help="wipe DB first")
    a = ap.parse_args()
    if a.fresh and os.path.exists(a.db):
        os.remove(a.db)
    s = Store(a.db)
    load(a.file, s, a.platform)
    s.close()
