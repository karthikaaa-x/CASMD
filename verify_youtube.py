#!/usr/bin/env python3
"""
Zero-dependency live check for the YouTube Data API (stdlib only — no pip install).

Run this in YOUR OWN terminal (where you have normal internet) to confirm your
free API key + topic + date range return real data before the full pipeline run.

    export YT_API_KEY=AIza...            # (Windows: set YT_API_KEY=AIza...)
    python verify_youtube.py --topic "crypto scam" --start 2026-11-06 --end 2026-11-20

It prints how many videos matched and a few titles + engagement. If this works,
the full pipeline (`python -m casmd.run --live ...`) will work too.
"""
import os
import sys
import json
import argparse
import urllib.parse
import urllib.request

BASE = "https://www.googleapis.com/youtube/v3"


def _get(path, params):
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300]
        sys.exit(f"API error {e.code}: {msg}")
    except Exception as e:
        sys.exit(f"Network error: {e}  (are you online / is the key set?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--key", default=os.environ.get("YT_API_KEY"))
    a = ap.parse_args()
    if not a.key:
        sys.exit("No key. Set YT_API_KEY or pass --key.")

    search = _get("search", {
        "part": "id", "q": a.topic, "type": "video", "order": "date",
        "publishedAfter": f"{a.start}T00:00:00Z",
        "publishedBefore": f"{a.end}T23:59:59Z",
        "maxResults": 25, "key": a.key,
    })
    ids = [i["id"]["videoId"] for i in search.get("items", [])]
    print(f"\n[ok] key valid. '{a.topic}' {a.start}..{a.end}: "
          f"{len(ids)} videos in this page "
          f"(~{search.get('pageInfo', {}).get('totalResults', '?')} total matches)\n")
    if not ids:
        print("No videos in that window — try a broader topic or wider dates.")
        return

    vids = _get("videos", {"part": "snippet,statistics",
                           "id": ",".join(ids), "key": a.key})
    for v in vids.get("items", [])[:8]:
        sn, st = v["snippet"], v.get("statistics", {})
        print(f"  • {sn['title'][:72]}")
        print(f"    {sn['channelTitle']} | {sn['publishedAt'][:10]} | "
              f"{st.get('viewCount','0')} views, {st.get('commentCount','0')} comments")
    print("\nIf you see titles above, run the full pipeline:")
    print(f'  python -m casmd.run --live --topic "{a.topic}" '
          f'--start {a.start} --end {a.end}\n')


if __name__ == "__main__":
    main()
