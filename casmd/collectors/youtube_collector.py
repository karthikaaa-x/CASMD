"""
YouTube collector (Data API v3).

Official, free (10k quota units/day). Returns videos, channels, publish dates,
engagement, tags and comment threads. Needs an API key in YT_API_KEY.

Incident-aware behaviour (important):
  * Searches with EVERY incident keyword (primary + additional), deduplicating
    videos by video id.
  * Fetches video details + channel metadata (creation date, avatar, description).
  * Scores each video's incident relevance (lightweight gate) and collects
    COMMENTS ONLY for videos that pass. This is deliberate: comments from
    unrelated videos must never enter the incident dataset or be mistaken for
    coordination. Every comment keeps a link to its parent video (`parent_id`).
  * Stores the raw API payload in `raw` for later investigation.

Quota notes:
  * search.list costs 100 units/call  -> ~100 searches/day on the free tier
  * videos.list / channels.list / commentThreads.list cost 1 unit/call
So we search sparingly (one paginated search per keyword) and fan out to the
cheap endpoints.

Dependencies: google-api-python-client
"""

from __future__ import annotations

import os
import argparse
from datetime import datetime

from ..schema import Post, Account, Media
from ..store import Store
from ..utils import stable_id
from ..config import Config, Incident
from ..analysis import relevance
from .base import RateLimiter, with_backoff


def collect(incident: Incident, cfg: Config, store: Store,
            max_videos: int = 200, max_comments_per_video: int = 100) -> int:
    try:
        from googleapiclient.discovery import build
    except ImportError:
        raise SystemExit("google-api-python-client not installed "
                         "(`pip install google-api-python-client`).")

    key = os.environ.get("YT_API_KEY")
    if not key:
        raise SystemExit("Set YT_API_KEY environment variable.")

    yt = build("youtube", "v3", developerKey=key, cache_discovery=False)
    limiter = RateLimiter(rate=5, per=1.0)

    published_after = f"{incident.date_start}T00:00:00Z"
    published_before = f"{incident.date_end}T23:59:59Z"

    # 1) Search with every keyword, dedup by video id.
    video_ids: list[str] = []
    seen = set()
    for kw in incident.all_keywords():
        page_token = None
        pulled = 0
        while len(video_ids) < max_videos and pulled < 100:
            limiter.acquire()
            try:
                search = with_backoff(
                    yt.search().list(
                        q=kw, part="id", type="video", order="date",
                        publishedAfter=published_after,
                        publishedBefore=published_before,
                        maxResults=50, pageToken=page_token).execute)
            except Exception as e:  # noqa: BLE001
                print(f"[youtube] search '{kw}' stopped: {type(e).__name__}: {e}")
                break
            for it in search.get("items", []):
                vid = it.get("id", {}).get("videoId")
                if vid and vid not in seen:
                    seen.add(vid)
                    video_ids.append(vid)
            pulled += len(search.get("items", []))
            page_token = search.get("nextPageToken")
            if not page_token:
                break
    video_ids = video_ids[:max_videos]
    print(f"[youtube] {len(video_ids)} unique videos across "
          f"{len(incident.all_keywords())} keyword(s) in "
          f"{incident.date_start}..{incident.date_end}")
    if not video_ids:
        return 0

    # 2) Video details.
    channel_ids: set[str] = set()
    vid_items = []
    for i in range(0, len(video_ids), 50):
        limiter.acquire()
        vr = with_backoff(
            yt.videos().list(part="snippet,statistics",
                             id=",".join(video_ids[i:i + 50])).execute)
        vid_items += vr.get("items", [])

    relevant_video_ids = []
    n = 0
    for v in vid_items:
        sn, st = v["snippet"], v.get("statistics", {})
        channel_ids.add(sn["channelId"])
        store.upsert_account(Account(
            account_id=f"yt:{sn['channelId']}", platform="youtube", kind="channel",
            handle=sn.get("channelTitle"), display_name=sn.get("channelTitle")))

        thumbs = sn.get("thumbnails", {})
        thumb_url = (thumbs.get("high") or thumbs.get("medium")
                     or thumbs.get("default") or {}).get("url")
        media = [Media("video", url=f"https://youtube.com/watch?v={v['id']}",
                       media_id=f"ytvid:{v['id']}")]
        if thumb_url:
            media.append(Media("image", url=thumb_url,
                               media_id=f"ytthumb:{v['id']}",
                               phash=None, sha256=stable_id(thumb_url, 16)))
        title = sn.get("title", "")
        desc = sn.get("description", "")
        tags = sn.get("tags", [])
        post = Post(
            post_id=f"yt:{v['id']}", platform="youtube", account_id=f"yt:{sn['channelId']}",
            kind="video",
            timestamp=datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")),
            text=f"{title}\n{desc}", lang=sn.get("defaultAudioLanguage"),
            media=media,
            likes=int(st.get("likeCount", 0)), views=int(st.get("viewCount", 0)),
            replies=int(st.get("commentCount", 0)),
            url=f"https://youtube.com/watch?v={v['id']}",
            raw={"snippet": sn, "statistics": st, "tags": tags})
        store.upsert_post(post)
        n += 1

        # Gate: only collect comments for videos that look incident-relevant.
        score = relevance.quick_relevance(incident, f"{title} {desc}", tags)
        if score >= cfg.review_threshold:
            relevant_video_ids.append(v["id"])
    store.commit()
    print(f"[youtube] {len(relevant_video_ids)}/{len(vid_items)} videos passed "
          f"the relevance gate; collecting their comments only")

    # 3) Comments ONLY for relevant videos.
    for vid in relevant_video_ids:
        n += _collect_comments(yt, vid, store, limiter, channel_ids,
                               max_comments_per_video)
    store.commit()

    # 4) Channel enrichment (creation date, avatar url, description, links).
    _enrich_channels(yt, channel_ids, store, limiter)
    store.commit()
    return n


def _collect_comments(yt, video_id, store, limiter, channel_ids, max_comments):
    try:
        limiter.acquire()
        resp = with_backoff(
            yt.commentThreads().list(
                part="snippet", videoId=video_id,
                maxResults=min(max_comments, 100), textFormat="plainText").execute)
    except Exception:
        return 0  # comments disabled on the video
    cnt = 0
    for item in resp.get("items", []):
        c = item["snippet"]["topLevelComment"]["snippet"]
        ch = c.get("authorChannelId", {}).get("value", "unknown")
        if ch != "unknown":
            channel_ids.add(ch)
        store.upsert_account(Account(
            account_id=f"yt:{ch}", platform="youtube", kind="user",
            handle=c.get("authorDisplayName"),
            display_name=c.get("authorDisplayName")))
        store.upsert_post(Post(
            post_id=f"yt:comment:{item['id']}", platform="youtube",
            account_id=f"yt:{ch}", kind="comment",
            timestamp=datetime.fromisoformat(c["publishedAt"].replace("Z", "+00:00")),
            text=c.get("textDisplay", ""), likes=int(c.get("likeCount", 0)),
            url=f"https://youtube.com/watch?v={video_id}&lc={item['id']}",
            reply_to=f"yt:{video_id}", parent_id=f"yt:{video_id}",
            raw={"comment": c}))
        cnt += 1
    return cnt


def _enrich_channels(yt, channel_ids, store, limiter):
    import re
    ids = list(channel_ids)
    url_re = re.compile(r"https?://[^\s]+")
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        limiter.acquire()
        try:
            resp = with_backoff(
                yt.channels().list(part="snippet", id=",".join(batch)).execute)
        except Exception:
            continue
        for ch in resp.get("items", []):
            sn = ch.get("snippet", {})
            created = sn.get("publishedAt")
            thumb = (sn.get("thumbnails", {}).get("default", {}) or {}).get("url")
            desc = sn.get("description", "")
            links = url_re.findall(desc)
            # URL-hash stand-in for the avatar: identical avatar URLs collide, so
            # exact avatar reuse is detectable. True visual matching needs the
            # media engine to download + hash the image (see analysis/media.py).
            phash = stable_id(thumb, 8) if thumb else None
            store.update_account_meta(
                f"yt:{ch['id']}",
                created_at=created.replace("Z", "+00:00") if created else None,
                phash=phash, description=desc, external_links=links,
                profile_photo_url=thumb)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", required=True)
    ap.add_argument("--keywords", default="", help="comma-separated extra terms")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--db", default="data/casmd.sqlite")
    a = ap.parse_args()
    inc = Incident(name="cli", primary_keyword=a.primary,
                   additional_keywords=[k for k in a.keywords.split(",") if k],
                   date_start=a.start, date_end=a.end)
    s = Store(a.db)
    collect(inc, Config(incident=inc), s)
    s.close()
