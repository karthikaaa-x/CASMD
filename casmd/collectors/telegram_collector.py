"""
Telegram collector (Telethon / MTProto) — incident-aware.

Given an incident (keywords + date range) this collects matching messages. Two
modes, combined:

  1. Global search  — messages.SearchGlobalRequest(q=keyword) for each keyword:
     Telegram's own public search across content your account can reach. NOT an
     exhaustive index — coverage is recorded and reported, never overstated.
  2. Per-channel    — if channels are supplied, each is searched per keyword, or
     (with tg_all) swept entirely across the date range.

For every message we preserve the amplification structure that makes Telegram
valuable for tracing misinformation:
  * forward_from  (which channel/account a message was forwarded from)
  * reply_to      (reply relationships)
  * kind flag     ("message" with raw.msg_kind in {original, forward}) so a
    forward is never confused with an independent upload.
Views, forwards, reactions, media ids and channel metadata (subscriber count,
creation date, profile photo, description) are collected where accessible.

Credentials are FREE from https://my.telegram.org (TG_API_ID / TG_API_HASH).
"""

from __future__ import annotations

import os
import argparse
from datetime import datetime, timezone

from ..schema import Post, Account, Media
from ..store import Store
from ..utils import stable_id
from ..config import Config, Incident
from .base import RateLimiter


def collect(incident: Incident, cfg: Config, store: Store,
            channels: list[str] | None = None, limit: int = 1000,
            use_search: bool = True) -> int:
    try:
        from telethon.sync import TelegramClient
        from telethon.tl.types import InputPeerEmpty, InputMessagesFilterEmpty
        from telethon.tl.functions.messages import SearchGlobalRequest
    except ImportError:
        raise SystemExit("telethon not installed. `pip install telethon`")

    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not (api_id and api_hash):
        raise SystemExit("Set TG_API_ID and TG_API_HASH (free: my.telegram.org)")

    start_dt = datetime.fromisoformat(incident.date_start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(incident.date_end + "T23:59:59").replace(tzinfo=timezone.utc)
    limiter = RateLimiter(rate=20, per=1.0)
    keywords = incident.all_keywords() or [incident.primary_keyword]
    seen_posts: set[str] = set()
    n = 0
    coverage = {"mode": [], "keywords": keywords, "channels": channels or [],
                "notes": []}

    with TelegramClient("casmd_session", int(api_id), api_hash) as client:
        if channels:
            coverage["mode"].append("per_channel")
            for ch in channels:
                ch = ch.strip().lstrip("@")
                for kw in (keywords if use_search else [None]):
                    try:
                        kept = 0
                        for msg in client.iter_messages(
                                ch, search=kw, offset_date=end_dt):
                            limiter.acquire()
                            if msg.date and msg.date > end_dt:
                                continue
                            if msg.date and msg.date < start_dt:
                                break
                            got = _save(msg, store, ch, client, seen_posts)
                            n += got
                            kept += got
                            if kept >= limit:
                                break
                        _enrich_channel(client, ch, store)
                    except Exception as e:  # noqa: BLE001
                        print(f"[telegram] skip {ch} ({kw}): {type(e).__name__}: {e}")
                        continue
                store.commit()
        else:
            coverage["mode"].append("global_search")
            for kw in keywords:
                print(f"[telegram] GLOBAL search '{kw}' "
                      f"{incident.date_start}..{incident.date_end}")
                offset_rate, offset_id = 0, 0
                offset_peer = InputPeerEmpty()
                fetched = 0
                while fetched < limit:
                    limiter.acquire()
                    try:
                        res = client(SearchGlobalRequest(
                            q=kw, filter=InputMessagesFilterEmpty(),
                            min_date=start_dt, max_date=end_dt,
                            offset_rate=offset_rate, offset_peer=offset_peer,
                            offset_id=offset_id, limit=100))
                    except Exception as e:  # noqa: BLE001
                        print(f"[telegram] global '{kw}' stopped: {type(e).__name__}: {e}")
                        break
                    if not res.messages:
                        break
                    for msg in res.messages:
                        n += _save(msg, store, None, client, seen_posts)
                        fetched += 1
                    last = res.messages[-1]
                    offset_id = last.id
                    offset_rate = getattr(res, "next_rate", offset_rate)
                    store.commit()
                    if len(res.messages) < 100:
                        break

    if n == 0:
        coverage["notes"].append(
            "0 messages. Telegram's free API only searches public content your "
            "account can reach — not a full index. Join relevant channels or pass "
            "--channels with --tg-all.")
    print(f"[telegram] collected {n} messages (coverage: {', '.join(coverage['mode'])})")
    return n


def _save(msg, store, channel, client, seen_posts) -> int:
    if not (getattr(msg, "message", None) or getattr(msg, "media", None)):
        return 0
    from telethon.tl.types import User, Channel

    chan = channel or (getattr(msg, "chat", None)
                       and getattr(msg.chat, "username", None)) or "tg"
    post_id = f"tg:{chan}:{msg.id}"
    if post_id in seen_posts:
        return 0
    seen_posts.add(post_id)
    post_url = f"https://t.me/{chan}/{msg.id}"

    # Attribute to a user if present, else the channel itself.
    try:
        sender = msg.sender
    except Exception:
        sender = None
    if isinstance(sender, User):
        acc_id = f"tg:{sender.id}"
        store.upsert_account(Account(
            account_id=acc_id, platform="telegram", kind="user",
            handle=sender.username,
            display_name=((sender.first_name or "") + " " +
                          (sender.last_name or "")).strip(),
            raw={"tg_user_id": sender.id}))
    elif isinstance(sender, Channel):
        acc_id = f"tg:{sender.username or sender.id}"
        store.upsert_account(Account(
            account_id=acc_id, platform="telegram", kind="channel",
            handle=sender.username, display_name=sender.title,
            followers=getattr(sender, "participants_count", 0) or 0,
            raw={"tg_channel_id": sender.id}))
    else:
        acc_id = f"tg:{chan}"
        store.upsert_account(Account(
            account_id=acc_id, platform="telegram", kind="channel",
            handle=chan if chan != "tg" else None, display_name=chan))

    # Media (photo / video) with a stable media id.
    media = []
    if getattr(msg, "photo", None):
        mid = f"tgphoto:{getattr(msg.photo, 'id', msg.id)}"
        media.append(Media("image", url=post_url, media_id=mid))
    elif getattr(msg, "video", None) or getattr(msg, "video_note", None):
        doc = getattr(msg, "document", None)
        mid = f"tgvideo:{getattr(doc, 'id', msg.id)}"
        media.append(Media("video", url=post_url, media_id=mid))

    # Forward vs original.
    fwd = None
    msg_kind = "original"
    if getattr(msg, "forward", None) and msg.forward.from_id is not None:
        fwd = f"tg:{_peer_id(msg.forward.from_id)}"
        msg_kind = "forward"

    reply_to = None
    if getattr(msg, "reply_to", None) and getattr(msg.reply_to, "reply_to_msg_id", None):
        reply_to = f"tg:{chan}:{msg.reply_to.reply_to_msg_id}"

    # Reactions, where accessible.
    reactions = {}
    try:
        if getattr(msg, "reactions", None) and msg.reactions.results:
            for r in msg.reactions.results:
                emo = getattr(getattr(r, "reaction", None), "emoticon", "?")
                reactions[emo] = r.count
    except Exception:
        pass

    store.upsert_post(Post(
        post_id=post_id, platform="telegram", account_id=acc_id, kind="message",
        timestamp=msg.date.astimezone(timezone.utc),
        text=msg.message or "", media=media,
        shares=getattr(msg, "forwards", 0) or 0,
        views=getattr(msg, "views", 0) or 0,
        url=post_url, forward_from=fwd, reply_to=reply_to,
        raw={"channel": chan, "msg_kind": msg_kind, "reactions": reactions}))
    return 1


def _enrich_channel(client, ch, store):
    """Channel metadata: subscribers, creation date, profile photo, description."""
    try:
        from telethon.tl.functions.channels import GetFullChannelRequest
        ent = client.get_entity(ch)
        full = client(GetFullChannelRequest(ent))
        subs = getattr(full.full_chat, "participants_count", 0) or 0
        about = getattr(full.full_chat, "about", "") or ""
        acc_id = f"tg:{getattr(ent, 'username', None) or ch}"
        store.upsert_account(Account(
            account_id=acc_id, platform="telegram", kind="channel",
            handle=getattr(ent, "username", None),
            display_name=getattr(ent, "title", ch), followers=subs,
            description=about))
        import re
        links = re.findall(r"https?://[^\s]+", about)
        phash = stable_id(acc_id, 8)   # placeholder avatar id (see media engine)
        store.update_account_meta(
            acc_id, created_at=getattr(ent, "date", None),
            description=about, external_links=links, phash=phash)
    except Exception as e:  # noqa: BLE001
        print(f"[telegram] channel meta skip {ch}: {type(e).__name__}")


def _peer_id(peer) -> int:
    for attr in ("user_id", "channel_id", "chat_id"):
        if hasattr(peer, attr):
            return getattr(peer, attr)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", required=True)
    ap.add_argument("--keywords", default="")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--channels", default=None, help="comma-separated (optional)")
    a = ap.parse_args()
    inc = Incident(name="cli", primary_keyword=a.primary,
                   additional_keywords=[k for k in a.keywords.split(",") if k],
                   date_start=a.start, date_end=a.end)
    s = Store("data/casmd.sqlite")
    collect(inc, Config(incident=inc), s,
            channels=a.channels.split(",") if a.channels else None)
    s.close()
