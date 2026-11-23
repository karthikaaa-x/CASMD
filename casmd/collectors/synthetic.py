"""
Synthetic incident generator — a realistic ship-bombing misinformation event,
with ground-truth labels for evaluation.

It builds the four scenarios the brief specifies, by construction:

  Scenario 1 — Coordinated video dissemination (the network)
     Multiple YouTube channels upload the SAME ship-bombing video (one original,
     one re-encode, one cropped), with near-identical captions, in timed waves;
     the same video is then circulated and forwarded across two Telegram
     channels. These accounts also share creation windows and avatars.

  Scenario 2 — Organic discussion
     Real people discussing the incident in their own words — questions,
     disagreement about authenticity, and a legitimate news link.

  Scenario 3 — Unrelated activity
     A GTA-6 gaming video with generic comments ("First", "Nice video",
     "Amazing", "GTA 6 is amazing", "Best YouTubers ever") — some posted within
     seconds of each other to tempt a naive co-posting detector — plus unrelated
     Telegram chatter. None of it is about the incident.

  Scenario 4 — Debunking
     Accounts identifying the footage as old / AI-generated and sharing
     corrections.

Nothing here is a real person, account, video or institution. Media fingerprints
(SHA-256 / keyframe hashes) are synthetic constants, clearly not derived from any
real file — the generator never pretends to have downloaded anything.

`generate(incident)` returns (accounts, posts, ground_truth). `build(store, inc)`
writes them to the DB and saves the ground truth to data/synthetic_ground_truth.json.
Deterministic: a fixed RNG seed gives identical output every run.
"""

from __future__ import annotations

import os
import json
import random
from datetime import datetime, timedelta, timezone

from ..schema import Post, Account, Media
from ..utils import stable_id

UTC = timezone.utc
RNG = random.Random(1234)

# ---- synthetic media fingerprints (clearly not real files) ----------------- #
SHA_MAIN = stable_id("ship_bombing_video_original", 32)   # 64 hex
SHA_REENC = stable_id("ship_bombing_video_reencode", 32)
SHA_CROP = stable_id("ship_bombing_video_cropped", 32)
KF = [stable_id(f"shipvid_keyframe_{i}", 8) for i in range(6)]      # 16 hex each
KF_CROP = KF[:4] + [stable_id("crop_extra_1", 8), stable_id("crop_extra_2", 8)]
THUMB = stable_id("ship_bombing_thumbnail", 8)

# ---- coordinated caption templates (waves) --------------------------------- #
WAVE1 = ("BREAKING: Iranian naval ship attacked and BOMBED in the Gulf tonight. "
         "Share this ship bombing before they delete it! #ShipBombing #Iran")
WAVE2 = ("URGENT: footage confirms the Iranian ship was attacked and is sinking "
         "after the naval bombing. They are hiding the truth — spread this now!")


def _perturb(text, i):
    outs = [text, text.replace("BREAKING", "URGENT"), text + " !!",
            "🚨 " + text, text.replace("!", "!!"), text.replace("the", "THE", 1)]
    return outs[i % len(outs)]


def generate(incident):
    # Reset the RNG every call so output is identical no matter how many times
    # generate() runs in a single process (determinism guarantee).
    RNG.seed(1234)
    accounts, posts = [], []
    truth = {"coordinated_accounts": [], "relevant_posts": [],
             "irrelevant_posts": [], "media_cluster_posts": [],
             "scenario": {}}
    pid = [0]

    def P(**kw):
        pid[0] += 1
        kw.setdefault("post_id", f"{kw['platform'][:2]}:syn:{pid[0]}")
        p = Post(**kw)
        posts.append(p)
        return p

    def A(acc):
        accounts.append(acc)
        return acc

    def mark(p, scenario, relevant, coordinated=False):
        truth["scenario"][p.post_id] = scenario
        if relevant:
            truth["relevant_posts"].append(p.post_id)
        else:
            truth["irrelevant_posts"].append(p.post_id)

    base = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
    created_net = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)  # tight creation window

    # ---------------------------------------------------------------- #
    # Scenario 1 — coordinated network
    # ---------------------------------------------------------------- #
    AV_YT = stable_id("shared_avatar_yt", 8)
    AV_TG = stable_id("shared_avatar_tg", 8)

    yt_net = [
        ("yt:chanA", "Gulf News Now", SHA_MAIN, KF, AV_YT, 0),
        ("yt:chanB", "Maritime Watch", SHA_REENC, KF, AV_YT, 12),
        ("yt:chanC", "Breaking Intl", SHA_CROP, KF_CROP, stable_id("av_c", 8), 40),
    ]
    tg_net = [
        ("tg:tgC", "ShipAlertHQ", AV_TG, 120),       # 2h after base
        ("tg:tgD", "GulfTruth", AV_TG, 130),         # forwards from tgC
    ]

    coordinated = []
    # YouTube uploads (wave 1 video) + wave 2 re-assert
    for k, (aid, name, sha, kf, av, off) in enumerate(yt_net):
        A(Account(aid, "youtube", kind="channel", handle=name.replace(" ", ""),
                  display_name=name, created_at=created_net + timedelta(hours=k),
                  profile_photo_phash=av, followers=RNG.randint(50, 400),
                  description="ship bombing vessel attack coverage"))
        coordinated.append(aid)
        vmedia = [Media("video", url=f"https://youtube.com/watch?v=net{k}",
                        media_id=f"ytvid:net{k}", sha256=sha, keyframe_hashes=kf),
                  Media("image", url=f"https://i.ytimg.com/net{k}.jpg",
                        media_id=f"ytthumb:net{k}", phash=THUMB)]
        v = P(post_id=f"yt:net{k}", platform="youtube", account_id=aid, kind="video",
              timestamp=base + timedelta(minutes=off),
              text=_perturb(WAVE1, k), media=vmedia,
              likes=RNG.randint(80, 400), views=RNG.randint(4000, 20000),
              url=f"https://youtube.com/watch?v=net{k}")
        mark(v, 1, True, True)
        truth["media_cluster_posts"].append(v.post_id)
        # wave 2 (next day) re-assert, near-identical text
        w2 = P(platform="youtube", account_id=aid, kind="video",
               timestamp=base + timedelta(days=1, minutes=off % 10),
               text=_perturb(WAVE2, k),
               media=[Media("video", url=f"https://youtube.com/watch?v=net{k}b",
                            media_id=f"ytvid:net{k}b", sha256=sha, keyframe_hashes=kf)],
               likes=RNG.randint(40, 200), views=RNG.randint(2000, 9000),
               url=f"https://youtube.com/watch?v=net{k}b")
        mark(w2, 1, True, True)
        truth["media_cluster_posts"].append(w2.post_id)

    # Telegram circulation (wave 1 video, tgD forwards tgC) + wave 2
    for k, (aid, name, av, off) in enumerate(tg_net):
        A(Account(aid, "telegram", kind="channel", handle=name,
                  display_name=name, created_at=created_net + timedelta(hours=5 + k),
                  profile_photo_phash=av, followers=RNG.randint(500, 3000),
                  description="breaking ship attack updates https://ship-truth.example"))
        coordinated.append(aid)
        fwd = "tg:tgC" if aid == "tg:tgD" else None
        v = P(platform="telegram", account_id=aid, kind="message",
              timestamp=base + timedelta(minutes=off),
              text=_perturb(WAVE1, k + 3),
              media=[Media("video", url=f"https://t.me/{name}/10",
                           media_id=f"tgvideo:net{k}", sha256=SHA_MAIN,
                           keyframe_hashes=KF)],
              shares=RNG.randint(20, 90), views=RNG.randint(3000, 12000),
              url=f"https://t.me/{name}/10", forward_from=fwd,
              raw={"msg_kind": "forward" if fwd else "original"})
        mark(v, 1, True, True)
        truth["media_cluster_posts"].append(v.post_id)
        w2 = P(platform="telegram", account_id=aid, kind="message",
               timestamp=base + timedelta(days=1, minutes=5 + k),
               text=_perturb(WAVE2, k + 2),
               shares=RNG.randint(10, 50), views=RNG.randint(1000, 5000),
               url=f"https://t.me/{name}/11")
        mark(w2, 1, True, True)

    truth["coordinated_accounts"] = sorted(set(coordinated))

    # A few GENERIC comments on the (relevant) coordinated video — must NOT be
    # treated as coordination, and must not pollute narratives.
    for k in range(4):
        aid = f"yt:genfan{k}"
        A(Account(aid, "youtube", kind="user", handle=f"fan{k}",
                  display_name=f"fan{k}", created_at=datetime(2024, 1, 1, tzinfo=UTC)))
        c = P(platform="youtube", account_id=aid, kind="comment",
              timestamp=base + timedelta(minutes=5 + k),   # near-simultaneous
              text=["First!", "nice", "🔥🔥", "wow"][k],
              url="https://youtube.com/watch?v=net0", reply_to="yt:net0",
              parent_id="yt:net0")
        mark(c, 1, False)   # generic -> not a relevant incident post

    # ---------------------------------------------------------------- #
    # Scenario 2 — organic discussion (relevant, NOT coordinated)
    # ---------------------------------------------------------------- #
    ORGANIC = [
        "is this ship bombing video actually real? something feels off about it honestly",
        "saw the maritime attack clip going around today, genuinely not sure what to believe",
        "anyone have a credible source on the vessel explosion before i share it anywhere?",
        "the naval bombing footage is all over my feed, what is even going on in the gulf",
        "Reuters is reporting a cargo vessel explosion in the strait https://reuters.com/world/ship-x",
        "my cousin is a sailor and he says that ship attacked video looks staged to him",
        "hope the crew on that vessel is safe, the explosion in the clip looks massive",
        "why is nobody in mainstream media covering this ship bombing yet, strange",
        "the ship bombing story is trending but details are really thin right now",
        "watched the maritime attack video three times, the explosion timing seems odd",
        "someone said the vessel explosion was an accident not an attack, which is it",
        "following the naval bombing news closely, waiting for an official statement",
    ]
    for k, txt in enumerate(ORGANIC):
        plat = "youtube" if k % 2 == 0 else "telegram"
        aid = f"{plat[:2]}:org{k}"
        A(Account(aid, plat, kind="user", handle=f"user{k}", display_name=f"User {k}",
                  created_at=datetime(2021, RNG.randint(1, 12), RNG.randint(1, 28), tzinfo=UTC),
                  followers=RNG.randint(5, 4000)))
        kind = "comment" if plat == "youtube" else "message"
        parent = "yt:net0" if plat == "youtube" else None
        p = P(platform=plat, account_id=aid, kind=kind,
              timestamp=base + timedelta(hours=RNG.randint(2, 80), minutes=RNG.randint(0, 59)),
              text=txt, likes=RNG.randint(0, 120), shares=RNG.randint(0, 15),
              url=f"https://{plat}.example/{aid}",
              reply_to=parent, parent_id=parent)
        mark(p, 2, True)

    # ---------------------------------------------------------------- #
    # Scenario 3 — unrelated activity (MUST be excluded)
    # ---------------------------------------------------------------- #
    A(Account("yt:gameChan", "youtube", kind="channel", handle="GameZone",
              display_name="GameZone", created_at=datetime(2019, 5, 1, tzinfo=UTC),
              followers=500000))
    gv = P(post_id="yt:gta6", platform="youtube", account_id="yt:gameChan", kind="video",
           timestamp=base + timedelta(hours=3),
           text="GTA 6 official trailer reaction — INSANE graphics!! gameplay leak",
           media=[Media("video", url="https://youtube.com/watch?v=gta6",
                        media_id="ytvid:gta6", sha256=stable_id("gta6", 32))],
           likes=90000, views=5000000, url="https://youtube.com/watch?v=gta6")
    mark(gv, 3, False)
    GEN = ["First", "First comment", "Nice video", "Amazing", "GTA 6 is amazing",
           "Best YouTubers ever", "wow so cool", "🔥🔥🔥", "early gang", "who else here"]
    for k, txt in enumerate(GEN):
        aid = f"yt:gamer{k}"
        A(Account(aid, "youtube", kind="user", handle=f"gamer{k}",
                  display_name=f"gamer{k}",
                  created_at=datetime(2023, 6, 1, tzinfo=UTC) + timedelta(hours=k)))
        c = P(platform="youtube", account_id=aid, kind="comment",
              # near-simultaneous: tempts a naive co-posting detector
              timestamp=base + timedelta(hours=3, seconds=10 * k),
              text=txt, url="https://youtube.com/watch?v=gta6",
              reply_to="yt:gta6", parent_id="yt:gta6")
        mark(c, 3, False)
    UNREL = ["join my crypto pump channel for 100x gains t.me/cryptopump",
             "football results tonight: City 3 United 1, what a match",
             "free phone giveaway, click the link to claim now",
             "good morning everyone, have a blessed day ☀️",
             "selling concert tickets DM me", "new recipe video is up, check it out"]
    for k, txt in enumerate(UNREL):
        aid = f"tg:noise{k}"
        A(Account(aid, "telegram", kind="channel", handle=f"noise{k}",
                  display_name=f"noise{k}", created_at=datetime(2022, 1, 1, tzinfo=UTC)))
        p = P(platform="telegram", account_id=aid, kind="message",
              timestamp=base + timedelta(hours=RNG.randint(1, 60)),
              text=txt, url=f"https://t.me/noise{k}/1")
        mark(p, 3, False)

    # ---------------------------------------------------------------- #
    # Scenario 4 — debunking (relevant)
    # ---------------------------------------------------------------- #
    DEBUNK = [
        "FACT CHECK: this 'ship bombing' clip is OLD footage from a 2019 naval exercise, not recent",
        "that viral maritime attack video is AI-generated — look at the warped railings and smoke",
        "correction: the ship attacked footage is unrelated to the current conflict, it's an old drill",
        "debunked: the vessel explosion video has been circulating since 2021, do not share it as new",
        "please stop spreading the naval bombing clip, independent fact-checkers confirmed it is a deepfake",
    ]
    for k, txt in enumerate(DEBUNK):
        plat = "telegram" if k % 2 else "youtube"
        aid = f"{plat[:2]}:deb{k}"
        A(Account(aid, plat, kind="user", handle=f"factcheck{k}",
                  display_name=f"FactCheck {k}",
                  created_at=datetime(2020, RNG.randint(1, 12), 1, tzinfo=UTC),
                  followers=RNG.randint(100, 20000)))
        kind = "comment" if plat == "youtube" else "message"
        parent = "yt:net0" if plat == "youtube" else None
        p = P(platform=plat, account_id=aid, kind=kind,
              timestamp=base + timedelta(hours=RNG.randint(6, 100)),
              text=txt, likes=RNG.randint(5, 300),
              url=f"https://{plat}.example/{aid}", reply_to=parent, parent_id=parent)
        mark(p, 4, True)

    return accounts, posts, truth


def build(store, incident):
    accounts, posts, truth = generate(incident)
    for a in accounts:
        store.upsert_account(a)
    for p in posts:
        store.upsert_post(p)
    store.commit()
    os.makedirs("data", exist_ok=True)
    with open("data/synthetic_ground_truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=2)
    print(f"[synthetic] wrote {len(accounts)} accounts, {len(posts)} posts "
          f"(coordinated accounts: {len(truth['coordinated_accounts'])}); "
          f"ground truth -> data/synthetic_ground_truth.json")
    return truth


if __name__ == "__main__":
    from ..store import Store
    from ..config import Incident
    inc = Incident(name="Ship bombing deepfake incident",
                   primary_keyword="ship bombing",
                   additional_keywords=["vessel explosion", "ship attacked",
                                        "maritime attack", "naval bombing",
                                        "Iranian ship", "cargo vessel explosion"],
                   date_start="2026-11-01", date_end="2026-11-20")
    s = Store("data/casmd.sqlite")
    s.reset()
    build(s, inc)
    s.close()
