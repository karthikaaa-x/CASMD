"""
Live collection orchestrator — YouTube and Telegram only.

Input is an Incident (keywords + date range). This fans the incident out to the
platform collectors that have credentials in the environment, and reports what it
got. Platforms without credentials are skipped with a clear message (never
silently). Returns (total_posts, platforms_used).

Credentials (both free):
    Telegram : TG_API_ID, TG_API_HASH   (my.telegram.org)
    YouTube  : YT_API_KEY               (console.cloud.google.com, free tier)

The platform list is modular: adding another platform later means adding a
collector module and a branch here. The shipped system supports only the two
platforms the brief requires.
"""

from __future__ import annotations

import os

from ..config import SUPPORTED_PLATFORMS


def collect(incident, cfg, store, tg_channels=None, tg_search=True,
            nicegram=False, nicegram_bot=None):
    total = 0
    used = []
    # Opt-in near-global Telegram search via a search bot (higher risk).
    if nicegram:
        try:
            from . import nicegram_collector
            n = nicegram_collector.collect(incident, cfg, store,
                                           bot=nicegram_bot) or 0
            total += n
            if n:
                used.append("telegram-bot")
        except SystemExit as e:
            print(f"[live] nicegram: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[live] nicegram: {e}")
    for platform in incident.platforms:
        if platform not in SUPPORTED_PLATFORMS:
            print(f"[live] {platform}: unsupported (only {SUPPORTED_PLATFORMS})")
            continue
        try:
            if platform == "youtube" and os.environ.get("YT_API_KEY"):
                from . import youtube_collector
                n = youtube_collector.collect(incident, cfg, store) or 0
                total += n
                used.append("youtube")
            elif platform == "telegram" and os.environ.get("TG_API_ID"):
                from . import telegram_collector
                n = telegram_collector.collect(incident, cfg, store,
                                               channels=tg_channels,
                                               use_search=tg_search) or 0
                total += n
                used.append("telegram")
            else:
                print(f"[live] {platform}: no credentials set — skipped "
                      f"(see README for the free env vars)")
        except SystemExit as e:
            print(f"[live] {platform}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"[live] {platform}: collection error: {e}")
    return total, used
