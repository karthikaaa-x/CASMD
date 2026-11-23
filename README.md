# CASMD — Coordinated Activity & Disinformation Detection System

CASMD is an **incident-centric** SOCMINT tool for **YouTube and Telegram**. You
give it an *incident* (a name, keywords, a description and a date range) and it
identifies:

* suspicious videos/media circulating across multiple accounts,
* reuploads of identical or modified videos,
* coordinated dissemination of the same media or narrative,
* the accounts and channels amplifying it,
* the earliest observed posts/accounts associated with the incident,
* how a narrative or media asset spreads **between YouTube and Telegram**,
* potential misinformation, manipulated-media and deepfake-related claims.

### The central principle

> **First establish that collected content is about the same incident. Only then
> investigate whether the accounts distributing it are coordinated.**

Accounts are **never** classified as coordinated just because they posted within
minutes of each other. Temporal proximity is counted only when the posts are
*independently established as incident-related and share real content* (the same
media, the same narrative, or near-identical text). This is the single most
important behaviour of the system and is enforced structurally (see
[Coordination](#8-coordination-detection)).

---

## Table of contents

1. [Quick start](#quick-start)
2. [What you should see on the demo](#what-you-should-see-on-the-demo)
3. [Architecture](#architecture)
4. [Project structure](#project-structure)
5. [Input interface](#input-interface)
6. [Getting the free API credentials](#getting-the-free-api-credentials)
7. [Running live collection](#running-live-collection)
8. [Running on a dataset you already have](#running-on-a-dataset-you-already-have)
9. [The detection algorithms](#the-detection-algorithms)
10. [Exports](#exports)
11. [Testing & evaluation](#testing--evaluation)
12. [API limitations & what cannot be reliably detected](#api-limitations--what-cannot-be-reliably-detected)
13. [Legal & ethics](#legal--ethics)

---

## Quick start

```bash
python -m pip install -r requirements.txt          # numpy, networkx, pytest

# Run the self-contained synthetic demonstration (no API keys, deterministic):
python -m casmd.run --demo

# Open the dashboard:
#   output/dashboard.html
```

The demo builds a realistic synthetic **ship-bombing misinformation incident**
(four scenarios, with ground-truth labels), runs the whole pipeline and writes
the dashboard and all exports to `output/`.

Run the automated tests and the quantitative evaluation:

```bash
python -m pytest -q          # behavioural tests (relevance, coordination, media, e2e)
python -m casmd.evaluate     # precision/recall vs the synthetic ground truth
```

---

## What you should see on the demo

```
[relevance] relevant=27 ... irrelevant=21 (generic=13)
[media] 2 media cluster(s) (shared across >=2 accounts: 2)
[narratives] 4 narrative(s)
[coordination] 1 strong, 0 possible group(s); 5 flagged accounts
```

And from `python -m casmd.evaluate`:

```
[RELEVANCE]    precision=1.00  recall=1.00  f1=1.00   (TP=27 FP=0 FN=0)
[COORDINATION] precision=1.00  recall=1.00  f1=1.00   (TP=5  FP=0 FN=0)
[MEDIA]        8/8 reuploaded copies grouped in one cluster (purity=1.0)
[ORIGIN]       earliest observed = yt:net0 (coordinated=True)
```

The point of these numbers is **what they get right by exclusion**: the
near-simultaneous generic GTA-6 comments, the organic discussion and the
debunkers are all correctly **kept out** of the coordinated group. That is the
false-positive failure mode this system is built to avoid.

---

## Architecture

```
            ┌──────────────┐
  Incident  │  COLLECTION  │   youtube_collector / telegram_collector
  (keywords,│              │   import_data (CSV/JSON) / synthetic (demo)
   dates)   └──────┬───────┘
                   ▼
            ┌──────────────┐   analysis/relevance.py
            │  RELEVANCE   │   "is this the same incident?"  3 categories
            └──────┬───────┘   (relevant / review / irrelevant), parent-gating
                   ▼
            ┌──────────────┐   analysis/media.py
            │    MEDIA     │   SHA-256 + keyframe pHash + thumbnail dHash
            │ CORRELATION  │   -> media clusters (promote relevance)
            └──────┬───────┘
          ┌────────┴─────────┐
          ▼                  ▼
   ┌─────────────┐   ┌────────────────┐  analysis/narratives.py,
   │  NARRATIVES │   │  COORDINATION  │  analysis/coordination.py
   │  (+ stance) │   │ (incident-only)│  6 detectors, fused, classified
   └──────┬──────┘   └───────┬────────┘
          └────────┬─────────┘
                   ▼
            ┌──────────────┐   analysis/origin.py
            │  ORIGIN &    │   earliest observed, propagation graph, timeline
            │ PROPAGATION  │
            └──────┬───────┘
                   ▼
     exports (8 files) + self-contained HTML dashboard
```

Collection only ever *writes* to the SQLite store; analysis *reads* posts and
writes back its derived records. Collect once, analyze (and re-tune) many times.
Everything downstream of collection is **deterministic** — repeated runs on the
same data give identical results.

All tunable thresholds live in `casmd/config.py` (`Config`), so every decision is
transparent and auditable.

---

## Project structure

```
casmd/
  schema.py          Post / Account / Media + MediaAsset / MediaCluster, relevance fields
  config.py          Incident (input) + Config (all thresholds)
  store.py           SQLite storage (posts, accounts, clusters, groups, propagation…)
  run.py             orchestrator / CLI  (python -m casmd.run)
  evaluate.py        precision/recall harness (python -m casmd.evaluate)
  export.py          writes the 8 export files
  dashboard.py       self-contained HTML dashboard (sections A–F)
  webapp.py          optional Flask UI
  utils.py           hashing, Hamming distance, text/string similarity
  collectors/
    youtube_collector.py   YouTube Data API v3 (keyword search, comments gated on relevance)
    telegram_collector.py  Telethon/MTProto (global + per-channel, forwards preserved)
    live.py                orchestrates YouTube + Telegram collection
    import_data.py         import a CSV/JSON dataset onto the schema
    synthetic.py           the synthetic ship-bombing incident + ground truth
    base.py                rate limiter + backoff
  analysis/
    relevance.py     incident relevance engine (HIGH PRIORITY)
    media.py         media correlation & matching engine (HIGH PRIORITY)
    narratives.py    narrative clustering + stance
    coordination.py  incident-centric coordination detection (REBUILT)
    origin.py        origin + cross-platform propagation + timeline
    insight.py       per-narrative / per-group readable findings
    textvec.py       numpy-only TF-IDF + clustering
    entities.py      hashtags / mentions / URLs / domains
    sentiment.py     lexicon mood (for narrative colour)
tests/               pytest suite (relevance, coordination, media, end-to-end)
examples/            make_sample.py + a sample importable dataset
```

Only **YouTube and Telegram** are collected. X / Instagram / TikTok / Facebook
are intentionally not implemented. The collector layer is modular (one module per
platform, dispatched by `live.py`), so another platform *could* be added later,
but the shipped system supports the two the brief requires.

---

## Input interface

An investigation is described by an `Incident` (see `casmd/config.py`):

| field                 | meaning                                  |
|-----------------------|------------------------------------------|
| `name`                | incident name                            |
| `primary_keyword`     | primary keyword / search phrase          |
| `additional_keywords` | related terms (optional, list)           |
| `description`         | incident description (optional)          |
| `date_start` / `date_end` | date range (YYYY-MM-DD)              |
| `platforms`           | `("youtube", "telegram")`                |

On the CLI:

```bash
python -m casmd.run --live \
  --incident   "Ship bombing deepfake incident" \
  --primary    "ship bombing" \
  --keywords   "vessel explosion,ship attacked,maritime attack,naval bombing,Iranian ship,cargo vessel explosion" \
  --description "A possibly manipulated video of a ship being bombed is circulating." \
  --start 2026-11-01 --end 2026-11-20 \
  --platforms youtube --platforms telegram
```

Searching uses **every** keyword (primary + additional), not one exact string.

---

## Scoping a good incident (important)

CASMD is **incident-centric**, not a topic monitor. It is built to show one
thing spreading — a specific video, claim or event — across accounts. Give it a
**bounded incident** and every section fills in; give it a broad evergreen term
and the media/coordination/timeline sections will be empty because there is no
single thing propagating.

| Works well (bounded incident) | Reads as empty/noisy (broad topic) |
|-------------------------------|------------------------------------|
| `"ship bombing"` + tight dates around the event | `"GTA"` over three months |
| `"Acme Bank collapse"` the week it trended | `"Acme Bank"` all year |
| `"<person> deepfake"` when a specific clip spread | `"<person>"` in general |

Rules of thumb: pick a phrase tied to a **specific event, claim or piece of
media**; add 3–6 related terms; and set the **date window to when it happened**
(days/weeks, not months). If the dashboard says *"Weak signals only — no strong
coordination … looks more like a broad topic than a bounded incident,"* that is
the system telling you to narrow the query. A broad topic query correctly
produces **no** coordinated groups and neutral *General discussion* narratives —
that is the right answer, not a failure.

## Getting the free API credentials

### YouTube (Data API v3 — free)

1. Go to <https://console.cloud.google.com/>, create (or pick) a project.
2. **APIs & Services → Library → “YouTube Data API v3” → Enable.**
3. **APIs & Services → Credentials → Create credentials → API key.**
4. Copy the key and export it:
   ```bash
   export YT_API_KEY=AIza...          # Windows: set YT_API_KEY=AIza...
   ```
Free quota is 10,000 units/day. `search.list` costs 100 units/call; video,
channel and comment reads cost 1 each — so CASMD searches sparingly (one
paginated search per keyword) and fans out to the cheap endpoints.

You can sanity-check your key with the bundled zero-dependency script:
```bash
python verify_youtube.py --topic "ship bombing" --start 2026-11-01 --end 2026-11-20
```

### Telegram (MTProto via Telethon — free)

1. Go to <https://my.telegram.org/> and log in with your phone number.
2. **API development tools** → create an app → copy `api_id` and `api_hash`.
3. Export them:
   ```bash
   export TG_API_ID=1234567
   export TG_API_HASH=0123456789abcdef0123456789abcdef
   ```
On first run Telethon will ask for your phone + a login code (one-time) and cache
a `casmd_session.session` file. Use an account you are comfortable using for
research.

---

## Running live collection

```bash
export YT_API_KEY=...            # at least one platform's creds
export TG_API_ID=...  TG_API_HASH=...

# Global keyword search on both platforms:
python -m casmd.run --live --incident "..." --primary "ship bombing" \
   --keywords "vessel explosion,maritime attack" --start 2026-11-01 --end 2026-11-20

# Telegram: search specific public channels instead of global search:
python -m casmd.run --live --primary "ship bombing" \
   --channels channel_a,channel_b --start 2026-11-01 --end 2026-11-20

# Telegram: pull ALL messages from those channels in the window (ignore keyword):
python -m casmd.run --live --primary "ship bombing" \
   --channels channel_a --tg-all --start 2026-11-01 --end 2026-11-20
```

Platforms without credentials are **skipped with a clear message**, never
silently. Collection respects published rate limits (token-bucket + exponential
backoff) and does not bypass any access restriction.

### Near-global Telegram search via a search bot (advanced, higher risk)

Telegram's official API only searches public content your account can reach. For
wider coverage you can drive a public Telegram **search bot** through your own
account (it sends each keyword, reads the replies, resolves the t.me links and
feeds them into the same pipeline):

```bash
export NICEGRAM_BOT=@SomeSearchBot
python -m casmd.run --live --nicegram --nicegram-bot @SomeSearchBot \
   --primary "ship bombing" --start 2026-11-01 --end 2026-11-20
```

⚠️ Automating a user account against a bot is against the spirit of Telegram's
ToS and can get the account rate-limited or banned. **Use a burner account.** The
bot's reply format is undocumented and may need tuning (`collectors/nicegram_collector.py`).
Results pass through the exact same relevance, media, coordination and
propagation analysis as every other source.

### Browser UI — run scans and view the dashboard without the terminal

```bash
pip install flask
python -m casmd.webapp        # open http://127.0.0.1:8000
```

The form takes the incident (name, keyword(s), optional description, dates),
platforms, API keys, Telegram channels, the `--tg-all` sweep and the Telegram
search bot, lists the detectors that will run, then executes the pipeline and
opens the generated dashboard. Keys are used only for that run and are never
stored.

---

## Running on a dataset you already have

Import a CSV/JSON of posts (flexible column names — see `collectors/import_data.py`)
onto the schema and analyze it with no credentials:

```bash
python examples/make_sample.py          # writes examples/sample_custom_dataset.csv

python -m casmd.run \
  --import examples/sample_custom_dataset.csv \
  --incident "Bridge collapse clip" --primary "bridge collapse" \
  --keywords "bridge explosion,bridge attack,collapsed bridge" \
  --start 2026-11-01 --end 2026-11-20
```

Media fingerprint columns (`media_sha256`, `media_phash`) are honoured so media
correlation works on imported data too.

---

## The detection algorithms

### 5. Incident relevance engine  (`analysis/relevance.py`)

Every post gets a score in `[0,1]` from transparent signals: **primary keyword**,
**related keywords**, **semantic similarity** (TF-IDF cosine to the incident
reference text), **entity overlap**, and — for YouTube comments — **parent-video
relevance**. It is assigned one of three decisions:

* `relevant`  (≥ `relevant_threshold`, default 0.45) → admitted,
* `review`    (≥ `review_threshold`, default 0.22) → borderline, for manual review,
* `irrelevant` → excluded from all downstream analysis.

Key rules, all enforced:

* **Generic / low-information text** ("first", "nice video", "wow", "GTA 6 is
  amazing") is detected and flagged `is_generic`; it can never be relevant on its
  own and is excluded from the content-based coordination detectors.
* **A YouTube comment is only admitted if its parent video is relevant.** This is
  what keeps "GTA 6 is amazing" under a gaming video out of a ship-bombing
  incident, even if it was posted at a suspicious time.
* **Shared media promotes relevance**: a post whose media is in a multi-account
  media cluster is promoted to relevant (real evidence it belongs to the
  incident), before comment gating runs.
* Each post stores its score, decision, reason and the signals behind it.

### 6. Media correlation & matching engine  (`analysis/media.py`)

Finds the same video/image across accounts and platforms, strongest match first:

1. **SHA-256** exact-file match → identical bytes (confidence **high**).
2. **Video keyframes** → perceptual hashes of FFmpeg-extracted keyframes; two
   videos are near-identical when enough keyframes match (handles re-encode /
   crop / resize). Confidence **high**.
3. **Perceptual image/thumbnail** (dHash Hamming distance) → visually similar
   image. Confidence **medium**.

Results are grouped into **media clusters** (union-find) with `media_id`,
`sha256`, `phash`, associated post/account ids, platforms, first-observed time,
match types and an evidence string. **Two videos are never declared identical on
matching thumbnails alone** — thumbnail-only clusters are flagged medium
confidence with an explicit caveat. In LIVE mode, downloading + hashing +
keyframes + optional OCR/transcription are attempted only when enabled
(`Config.download_media`, `enable_ocr`, `enable_transcribe`) and only when the
bytes are actually available — nothing is fabricated.

### 7. Narrative detection  (`analysis/narratives.py`)

Clusters the **relevant, non-generic** posts by TF-IDF cosine similarity into
narrative groups. For each narrative it derives a **stance**
(asserting / questioning / debunking) and a claim-type label — *Unverified
claim*, *Potential misinformation*, *Contradictory claim*, *Debunking content*,
*Verified information* (the last only when reputable-source citations are
present). It reports size, unique accounts, platform split, volume over time,
earliest post, example posts and the media clusters that appear in it. Nothing is
labelled "misinformation" merely for being suspicious or widely shared.

### 8. Coordination detection  (`analysis/coordination.py`) — rebuilt

Six detectors, each fully explainable, proposing weighted account-account links:

| detector | what it links on | strength |
|----------|------------------|----------|
| **A. shared_media** | accounts posting the same / near-identical media | content |
| **B. near_dup_caption** | accounts posting near-identical incident captions | content |
| **C. sync_dissemination** | repeatedly posting the same media/narrative in a short window | content (gated) |
| **D. cross_platform** | the same media/caption on YouTube **and** Telegram | content |
| **E. account_similarity** | creation burst / reused avatar / similar handles / shared links | **supporting only** |
| **F. amplification** | Telegram forwards, repeated forwarding, YT reply chains | content |

The links are fused into a weighted graph. **An edge is kept only if it carries
at least one content/media signal and reaches a minimum fused weight.** This is
what makes temporal proximity or profile coincidences *insufficient on their
own*: detector E and raw timing can corroborate but can never, by themselves,
create a group. Detector C only counts a synchronized event when the two posts
also share media, a narrative, or near-identical text.

Each connected component is classified as **strong coordination indicators**,
**possible coordination indicators**, or **insufficient evidence**, with a
**High/Medium/Low confidence whose calculation is spelled out** and a full,
human-readable **evidence trail** (which accounts, which signals, which posts). No
account is called a bot or malicious actor; findings are explicitly leads for
review, not proof.

### 9. Origin & propagation  (`analysis/origin.py`)

Reconstructs the earliest observed upload overall and per platform, the first
accounts, media reuploads, Telegram forwards, cross-platform jumps and new
narrative variants — as a **propagation graph** (typed edges) and a
**chronological timeline**. It is explicit everywhere that the earliest
*observed* post is **not** necessarily the original source of the footage.

---

## Exports

Written to `output/` (or `--out`):

| file | contents |
|------|----------|
| `report.json` | full combined report (incident, summary, narratives, media, groups, propagation, timeline) |
| `posts.json` / `posts.csv` | every collected post with relevance, narrative, media cluster and coordination group |
| `coordinated_groups.csv` | one row per group: classification, confidence, accounts, detectors, evidence |
| `media_clusters.json` | media correlation clusters with match types + evidence |
| `narratives.json` | narrative groups with stance and stats |
| `propagation_graph.json` | propagation nodes + typed edges |
| `timeline.json` | chronological incident timeline |
| `dashboard.html` | self-contained interactive dashboard (sections A–F) |

The **dashboard** is written for a general audience: a plain-English summary, a
"how to read this report" glossary, and a one-line *what this means* explanation
on every finding. It reads top-to-bottom as a briefing — incident overview &
verdict, a relevance funnel and platform split, media intelligence, narrative
analysis (with a trend chart), coordination analysis (with confidence meters and
evidence trails), origin & spread (timeline + cross-platform flow), and a
filterable post explorer. From the **Download** panel at the bottom you can export
any dataset (posts, coordinated groups, media clusters, narratives, timeline, or
the full report) as **JSON or CSV**, generated in the browser from the embedded
data — no re-run needed.

---

## Testing & evaluation

```bash
python -m pytest -q          # 17 behavioural tests
python -m casmd.evaluate     # precision/recall vs ground truth
```

The synthetic incident (`collectors/synthetic.py`) contains, by construction, the
four scenarios the brief specifies, each labelled with ground truth:

1. **Coordinated video dissemination** — 3 YouTube channels upload the same
   ship-bombing video (original, re-encode, cropped) with near-identical
   captions in timed waves; 2 Telegram channels circulate and forward it.
2. **Organic discussion** — real wording, questions, disagreement, a news link.
3. **Unrelated activity** — a GTA-6 gaming video with generic comments ("First",
   "Nice video", "GTA 6 is amazing") *posted seconds apart to tempt a naive
   co-posting detector*, plus unrelated Telegram chatter.
4. **Debunking** — accounts flagging the footage as old / AI-generated.

The evaluation reports precision/recall with explicit false positives and false
negatives for relevance, coordination, media clustering and origin. The tests
assert the hard requirements directly — e.g. *the generic GTA commenters are
never flagged as coordinated*, *comments under the gaming video are excluded*,
*every coordinated group has at least one content signal*. The realistic edge
cases are preserved on purpose; the tests are not tuned to force a pass.

---

## API limitations & what cannot be reliably detected

* **Telegram global search is not an exhaustive index.** The free API only
  searches public content your account can reach. CASMD records collection
  coverage and never claims completeness; for thorough coverage, search specific
  channels (`--channels`).
* **YouTube quota** (10k units/day) bounds how many keyword searches you can run.
* **Media downloads are off by default.** Without downloaded bytes, video
  matching falls back to thumbnails/metadata and is marked lower confidence;
  SHA-256 and keyframe matching need the actual files (LIVE mode, opt-in).
* **Same-person-on-both-platforms is not asserted** without explicit evidence;
  cross-platform links are between *content*, not identities.
* **Earliest observed ≠ original source.** Collected data cannot establish the
  true origin of a video; the system says so explicitly.
* **Coordination is inferred behaviour, not proof.** Groups are leads for human
  review. Account creation date, a shared avatar or posting time are *supporting*
  signals only and never sufficient alone.
* The offline narrative/sentiment models are deliberately simple and
  deterministic; install `sentence-transformers` for multilingual semantic
  narrative clustering.

---

## Legal & ethics

CASMD uses official, licensed APIs (YouTube Data API v3, Telegram MTProto) and
respects their rate limits, authentication and terms. It does not scrape behind
logins, bypass access restrictions, or fabricate media, account metadata or
platform evidence in live mode. All synthetic demo data is clearly synthetic and
represents no real person, account, video or institution. Findings describe
*behaviour* and are intended as leads for analyst review, not as determinations
about individuals.
