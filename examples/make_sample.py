"""
Generates examples/sample_custom_dataset.csv — a DIFFERENT incident from the
built-in demo (a fictional "bridge collapse" clip), so you can show the importer
+ full incident pipeline working on data the tool has never seen, on the two
supported platforms (YouTube + Telegram).

It contains a planted coordinated ring (same video file shared across channels,
near-identical captions, cross-platform forward) amid organic chatter, generic
comments and unrelated noise. Run:  python examples/make_sample.py

Then analyze it:
    python -m casmd.run --import examples/sample_custom_dataset.csv \
        --incident "Bridge collapse clip" --primary "bridge collapse" \
        --keywords "bridge explosion,bridge attack,collapsed bridge" \
        --start 2026-11-01 --end 2026-11-20
"""
import csv, os, random, hashlib
from datetime import datetime, timedelta

R = random.Random(7)
rows = []
pid = 0


def sid(s, n=8):
    return hashlib.blake2b(s.encode(), digest_size=n).hexdigest()


SHA = sid("bridge_clip_main", 32)
SHA2 = sid("bridge_clip_reencode", 32)
PH = sid("bridge_thumb", 8)


def add(platform, author, when, text, kind="", parent_id="", video_url="",
        sha256="", phash="", forward_from="", likes=0, forwards=0, replies=0,
        avatar=""):
    global pid
    pid += 1
    rows.append({
        "platform": platform, "post_id": f"{pid}", "author": author, "kind": kind,
        "created_at": when.strftime("%Y-%m-%d %H:%M:%S"), "text": text,
        "likes": likes, "forwards": forwards, "replies": replies,
        "url": f"https://{platform}.example/{author}/{pid}",
        "video_url": video_url, "media_sha256": sha256, "media_phash": phash,
        "forward_from": forward_from, "parent_id": parent_id, "avatar_url": avatar,
    })


CAP = ("BREAKING: major bridge collapse after explosion, dozens feared trapped. "
       "Share before they delete this! #BridgeCollapse")


def perturb(t, i):
    return [t, t.replace("BREAKING", "URGENT"), "🚨 " + t, t + " RT!!",
            t.replace("!", "!!")][i % 5]


# ---- coordinated ring: 3 YouTube channels + 2 Telegram channels, same video --
base = datetime(2026, 11, 6, 9, 0)
yt = [("GulfDesk", SHA), ("WorldAlertTV", SHA2), ("RapidNews24", SHA)]
for i, (ch, sha) in enumerate(yt):
    add("youtube", ch, base + timedelta(minutes=12 * i), perturb(CAP, i),
        kind="video", video_url=f"https://youtube.com/watch?v=brg{i}",
        sha256=sha, phash=PH, likes=R.randint(100, 400), replies=R.randint(50, 200),
        avatar="https://cdn.example/av/ring.png")
tg = [("BridgeAlertHQ", ""), ("TruthFeed", "tg:BridgeAlertHQ")]
for i, (ch, fwd) in enumerate(tg):
    add("telegram", ch, base + timedelta(hours=2, minutes=10 * i), perturb(CAP, i + 2),
        kind="message", video_url=f"https://t.me/{ch}/5", sha256=SHA, phash=PH,
        forward_from=fwd, forwards=R.randint(20, 80),
        avatar="https://cdn.example/av/ring2.png")

# ---- organic discussion (relevant; each person words it differently) ----
organic = [
    "is this bridge collapse video actually real? looks edited to me honestly",
    "anyone have a credible source on the bridge explosion? want to verify first",
    "the collapsed bridge footage is all over my feed today, what on earth happened",
    "praying for everyone near that bridge, the explosion in the clip looked huge",
    "mainstream media is weirdly silent on this bridge collapse so far, strange",
    "saw the bridge attack clip going around, genuinely not sure what to believe",
    "my brother drives over that bridge daily, hope the collapse reports are wrong",
    "why are details on the bridge explosion so thin right now, feels off",
    "someone said the collapsed bridge was an old demolition, can anyone confirm",
    "the bridge collapse is trending but every account says something different",
    "watched the bridge explosion video twice, the timing of the blast seems odd",
    "local radio has nothing on a bridge collapse near me, is this even recent",
    "following the bridge attack story closely, waiting for an official statement",
    "that bridge collapse clip spread fast, reminds me of old recycled disaster videos",
]
for i, txt in enumerate(organic):
    plat = "youtube" if i % 2 == 0 else "telegram"
    add(plat, f"user_{i}", base + timedelta(hours=R.randint(3, 70)), txt,
        kind="comment" if plat == "youtube" else "message",
        parent_id="1" if plat == "youtube" else "",
        likes=R.randint(0, 90))

# ---- generic comments on the real video (must not become coordination) ----
for i, t in enumerate(["First", "nice", "🔥🔥", "wow", "amazing"]):
    add("youtube", f"fan_{i}", base + timedelta(minutes=3 + i), t,
        kind="comment", parent_id="1")

# ---- unrelated noise (gaming video + generic comments; must be excluded) ----
add("youtube", "GameHub", base + timedelta(hours=4),
    "GTA 6 trailer breakdown — INSANE!!", kind="video",
    video_url="https://youtube.com/watch?v=gta", sha256=sid("gta", 32))
for i, t in enumerate(["First!", "Nice video", "GTA 6 is amazing",
                       "Best YouTubers ever", "early"]):
    add("youtube", f"gamer_{i}", base + timedelta(hours=4, seconds=10 * i), t,
        kind="comment", parent_id=str(pid - i))   # under the gaming video
for i, t in enumerate(["join my crypto channel t.me/pump", "football 3-1 tonight",
                       "free phone giveaway click here"]):
    add("telegram", f"noise_{i}", base + timedelta(hours=R.randint(1, 50)), t,
        kind="message")

out = os.path.join(os.path.dirname(__file__), "sample_custom_dataset.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"wrote {len(rows)} rows -> {out}")
