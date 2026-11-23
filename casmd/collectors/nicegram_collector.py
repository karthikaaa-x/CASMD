"""
Telegram search-bot collector  (OPT-IN, higher-risk) — incident-aware.

This drives a Telegram *search bot* (e.g. a public "search all channels" bot)
through your own Telethon session: it sends each incident keyword like a person
would, reads the bot's replies, pulls the t.me post links out, pages through a
few result pages, resolves each real message, and normalizes it into CASMD's
schema via the same `_save` the normal Telegram collector uses. That gets you
closer to "search across public channels" than the free official API allows.

⚠️  READ THIS FIRST
  * Automating a USER account to query a bot at volume is against the spirit of
    Telegram's ToS (userbot automation) and likely the bot's ToS too. It can get
    your account rate-limited, flagged or BANNED, and get you blocked by the bot.
  * USE A BURNER ACCOUNT, not your main. Keep the rate limit conservative.
  * The bot's reply format is undocumented and changes without notice, so the
    parser here is best-effort and heavily logged — expect to tune it once you
    see the real replies.

Config:
  NICEGRAM_BOT env var or bot= arg: the bot's @username (required — set it to the
  exact search bot you want to use; there is no safe default to guess).

Nothing runs unless the pipeline is invoked with nicegram enabled.

The results flow through the EXACT SAME downstream analysis as every other
source: incident relevance gating, media correlation, the six incident-centric
coordination detectors, narratives and propagation. This collector only changes
HOW messages are discovered, not how they are judged.
"""

from __future__ import annotations

import os
import re
import time
import argparse

from ..config import Config, Incident
from ..store import Store
from .base import RateLimiter

_TME = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{3,})/(\d+)", re.IGNORECASE)


def collect(incident: Incident, cfg: Config, store: Store, bot: str | None = None,
            limit: int = 500, max_pages: int = 5) -> int:
    try:
        from telethon.sync import TelegramClient
        from telethon.errors import FloodWaitError
    except ImportError:
        raise SystemExit("telethon not installed. `pip install telethon`")

    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not (api_id and api_hash):
        raise SystemExit("Set TG_API_ID and TG_API_HASH (free: my.telegram.org)")

    bot = bot or os.environ.get("NICEGRAM_BOT")
    if not bot:
        raise SystemExit("No search bot set. Pass --nicegram-bot @SomeSearchBot "
                         "or set NICEGRAM_BOT. There is no safe default to guess.")
    bot = bot.strip().lstrip("@")

    # Import _save lazily so this module imports even without telethon types.
    from .telegram_collector import _save

    limiter = RateLimiter(rate=1, per=3.0)   # deliberately gentle on the bot
    keywords = incident.all_keywords() or [incident.primary_keyword]
    seen_posts: set[str] = set()
    n = 0

    with TelegramClient("casmd_session", int(api_id), api_hash) as client:
        for kw in keywords:
            print(f"[nicegram] querying bot @{bot} for '{kw}'")
            try:
                limiter.acquire()
                client.send_message(bot, kw)
            except Exception as e:  # noqa: BLE001
                print(f"[nicegram] could not message @{bot}: {type(e).__name__}: {e}")
                break

            # Give the bot a moment to answer, then read its latest replies.
            pages = 0
            last_reply = None
            while pages < max_pages and n < limit:
                time.sleep(2.5)
                try:
                    replies = client.get_messages(bot, limit=3)
                except Exception as e:  # noqa: BLE001
                    print(f"[nicegram] read failed: {type(e).__name__}: {e}")
                    break
                # pick the newest message that actually came FROM the bot
                reply = next((m for m in replies if not m.out), None)
                if reply is None or reply.id == getattr(last_reply, "id", None):
                    break
                last_reply = reply

                links = _parse_links(reply)
                got = _resolve_and_save(client, links, store, seen_posts,
                                        incident, limiter)
                n += got
                print(f"[nicegram]   page {pages + 1}: {len(links)} links, "
                      f"saved {got} in-range messages")

                # try to page forward via an inline "next" button
                if not _click_next(reply):
                    break
                pages += 1
            store.commit()

    print(f"[nicegram] collected {n} messages via @{bot}")
    if n == 0:
        print("[nicegram] nothing parsed. The bot's reply format may differ from "
              "the t.me/<channel>/<id> links this parser expects — inspect a reply "
              "and adjust _parse_links / _click_next.")
    return n


def _parse_links(reply):
    """Pull (channel, msg_id) pairs out of a bot reply (text + button URLs)."""
    found = set()
    text = getattr(reply, "message", "") or ""
    for ch, mid in _TME.findall(text):
        found.add((ch, int(mid)))
    # inline buttons often carry the real t.me links as url buttons
    try:
        for row in (reply.reply_markup.rows if reply.reply_markup else []):
            for btn in row.buttons:
                url = getattr(btn, "url", None)
                if url:
                    for ch, mid in _TME.findall(url):
                        found.add((ch, int(mid)))
    except Exception:
        pass
    return sorted(found)


def _resolve_and_save(client, links, store, seen_posts, incident, limiter):
    saved = 0
    for ch, mid in links:
        try:
            limiter.acquire()
            msg = client.get_messages(ch, ids=mid)
        except Exception:
            continue
        if not msg:
            continue
        # keep only messages inside the incident date range
        from datetime import datetime, timezone
        start = datetime.fromisoformat(incident.date_start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(incident.date_end + "T23:59:59").replace(tzinfo=timezone.utc)
        if getattr(msg, "date", None) and not (start <= msg.date <= end):
            continue
        saved += _save(msg, store, ch, client, seen_posts)
    return saved


def _click_next(reply):
    """Best-effort: click an inline 'next/more' button to page forward."""
    try:
        for row in (reply.reply_markup.rows if reply.reply_markup else []):
            for btn in row.buttons:
                label = (getattr(btn, "text", "") or "").lower()
                if any(k in label for k in ("next", "more", "➡", "»", ">>")):
                    reply.click(text=getattr(btn, "text", None))
                    return True
    except Exception:
        pass
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", required=True)
    ap.add_argument("--keywords", default="")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--bot", default=None, help="search bot @username")
    a = ap.parse_args()
    inc = Incident(name="cli", primary_keyword=a.primary,
                   additional_keywords=[k for k in a.keywords.split(",") if k],
                   date_start=a.start, date_end=a.end)
    s = Store("data/casmd.sqlite")
    collect(inc, Config(incident=inc), s, bot=a.bot)
    s.close()
