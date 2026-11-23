"""
Incident-investigation dashboard — a single self-contained HTML file written for
a general audience.

Design goals:
  * plain language — every section and every finding is explained in one line,
    with a "How to read this report" glossary at the top;
  * clean, consistent inline-SVG icons (no emoji that render differently per OS);
  * downloads — each dataset can be exported as JSON or CSV from the page;
  * more visuals — a relevance funnel, platform split, narrative trend chart,
    confidence meters and media-reach bars, all drawn from the embedded data;
  * no external assets or network.

Sections:
  A. Media intelligence     (the same video/image across accounts)
  B. Narrative analysis     (the distinct claims, with stance)
  C. Coordination analysis  (groups acting together, with evidence)
  D. Origin & spread        (timeline + cross-platform propagation)
  E. Browse posts           (searchable / filterable table)
"""

from __future__ import annotations

import os
import json


def build(data, out_path):
    payload = json.dumps(data, ensure_ascii=False, default=str)
    html = _TEMPLATE.replace("/*__DATA__*/", payload)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CASMD — Incident Report</title>
<style>
 :root{
  --bg:#f4f5f8;--card:#fff;--ink:#141a27;--muted:#5b6578;--faint:#8a93a6;
  --line:#e7eaf0;--brand:#3d42d6;--brandbg:#eef0ff;
  --red:#d92d20;--redbg:#fef3f2;--amber:#b54708;--amberbg:#fff8ec;
  --green:#067a4d;--greenbg:#ecfdf4;--blue:#1570ef;--bluebg:#eff6ff;
  --yt:#ff0000;--tg:#2aabee;
 }
 *{box-sizing:border-box}
 html{scroll-behavior:smooth}
 body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.6 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
 .wrap{max-width:1000px;margin:0 auto;padding:0 20px 90px}
 a{color:var(--brand)}
 /* header */
 header.top{padding:30px 0 4px}
 .eyebrow{font-size:12px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--brand)}
 header.top h1{margin:4px 0 0;font-size:27px;font-weight:750;letter-spacing:-.02em}
 .meta{margin-top:8px;color:var(--muted);font-size:14px;display:flex;gap:14px;flex-wrap:wrap;align-items:center}
 .kw{display:inline-block;background:#eef0f4;border:1px solid var(--line);color:#48506a;
  border-radius:20px;padding:2px 11px;font-size:12px;margin:4px 5px 0 0}
 .pill{display:inline-flex;align-items:center;gap:6px;background:#fff;border:1px solid var(--line);
  border-radius:20px;padding:3px 11px;font-size:12.5px;font-weight:600;margin:4px 6px 0 0}
 /* plain summary */
 .lede{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 22px;margin:18px 0;font-size:15.5px;line-height:1.7}
 .lede b{font-weight:700}
 /* glossary */
 details.glossary{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:4px 18px;margin-bottom:18px}
 details.glossary>summary{cursor:pointer;list-style:none;padding:12px 0;font-weight:650;font-size:14px;display:flex;align-items:center;gap:8px}
 details.glossary>summary::-webkit-details-marker{display:none}
 .gl{display:grid;grid-template-columns:1fr;gap:10px;padding:4px 0 16px}
 @media(min-width:720px){.gl{grid-template-columns:1fr 1fr}}
 .gl div{font-size:13px;color:var(--muted)}.gl b{color:var(--ink)}
 /* verdict */
 .verdict{border-radius:16px;padding:20px 22px;margin:4px 0 22px;display:flex;gap:15px;align-items:flex-start}
 .verdict .ic{flex:none;margin-top:1px}.verdict h2{margin:0;font-size:19px;letter-spacing:-.01em}
 .verdict p{margin:5px 0 0;font-size:14px;opacity:.92}
 .verdict.High{background:var(--redbg);color:#7a271a}
 .verdict.Medium{background:var(--amberbg);color:#7a2e0e}
 .verdict.None{background:var(--greenbg);color:#064b31}
 /* stat tiles */
 .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:12px;margin-bottom:18px}
 .stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
 .stat .n{font-size:26px;font-weight:750;letter-spacing:-.02em}
 .stat .l{color:var(--muted);font-size:12px;margin-top:2px}
 .stat.flag .n{color:var(--red)}.stat.ok .n{color:var(--green)}
 /* viz row */
 .viz{display:grid;grid-template-columns:1fr;gap:14px;margin-bottom:34px}
 @media(min-width:720px){.viz{grid-template-columns:1fr 1fr}}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
 .panel h4{margin:0 0 4px;font-size:13px;font-weight:700}
 .panel .sub{color:var(--faint);font-size:12px;margin:0 0 12px}
 .funnel .bar{height:30px;border-radius:7px;display:flex;overflow:hidden;background:#eef0f4}
 .funnel .seg{height:100%}
 .funnel .row{display:flex;align-items:center;gap:8px;font-size:12.5px;margin-top:9px;color:var(--muted)}
 .funnel .sw{width:11px;height:11px;border-radius:3px;flex:none}
 .split .b{display:flex;align-items:center;gap:9px;margin-top:10px;font-size:13px}
 .split .track{flex:1;height:10px;background:#eef0f4;border-radius:6px;overflow:hidden}
 .split .fill{height:100%;border-radius:6px}
 /* sections */
 .sec-h{display:flex;align-items:center;gap:10px;margin:0 0 3px}
 .sec-h .tag{font-size:11px;font-weight:800;color:#fff;background:var(--brand);width:22px;height:22px;border-radius:7px;display:inline-flex;align-items:center;justify-content:center}
 h2.sec{font-size:17px;font-weight:700;margin:0;letter-spacing:-.01em}
 .sec-desc{color:var(--muted);font-size:13.5px;margin:4px 0 16px;max-width:760px}
 .block{margin-bottom:42px;scroll-margin-top:16px}
 /* cards */
 .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:17px 19px;margin-bottom:13px}
 .card.hi{border-left:4px solid var(--red)}.card.med{border-left:4px solid var(--amber)}
 .whatis{background:#f7f8fb;border:1px solid var(--line);border-radius:9px;padding:9px 12px;font-size:12.5px;color:var(--muted);margin:10px 0}
 .whatis b{color:var(--ink)}
 .badge{font-size:11px;font-weight:700;padding:3px 10px;border-radius:16px;letter-spacing:.02em;display:inline-flex;align-items:center;gap:5px;vertical-align:middle}
 .b-red{background:var(--redbg);color:var(--red)}.b-amber{background:var(--amberbg);color:var(--amber)}
 .b-green{background:var(--greenbg);color:var(--green)}.b-blue{background:var(--bluebg);color:var(--blue)}
 .b-gray{background:#eef0f4;color:#48506a}
 /* confidence meter */
 .meter{display:inline-flex;gap:3px;vertical-align:middle;margin-left:2px}
 .meter i{width:7px;height:7px;border-radius:50%;background:#d7dbe4}
 .meter.l1 i:nth-child(1),.meter.l2 i:nth-child(-n+2),.meter.l3 i{background:var(--amber)}
 .meter.l3 i{background:var(--red)}
 .sigs{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0 2px}
 .sig{font-size:12px;background:var(--greenbg);color:var(--green);border-radius:8px;padding:4px 10px;display:inline-flex;gap:6px;align-items:center}
 details.more{margin-top:11px}
 details.more>summary{cursor:pointer;color:var(--brand);font-size:13px;font-weight:600;list-style:none}
 details.more>summary::-webkit-details-marker{display:none}
 details.more>summary::before{content:"";display:inline-block;border:5px solid transparent;border-left-color:var(--brand);margin-right:7px;transform:translateY(-1px)}
 details.more[open]>summary::before{transform:rotate(90deg) translateX(-1px)}
 ul.trail{margin:9px 0 0;padding-left:4px;list-style:none;font-size:13px}
 ul.trail li{padding:5px 0 5px 20px;position:relative;color:#3a4257}
 ul.trail li::before{content:"";position:absolute;left:2px;top:11px;width:7px;height:7px;border-radius:50%;background:var(--brand)}
 .chips{margin-top:8px}
 .chip{display:inline-flex;align-items:center;gap:6px;background:#f1f2f6;border:1px solid var(--line);border-radius:16px;padding:3px 10px 3px 4px;font-size:12px;margin:3px 5px 0 0}
 .chip.coord{background:var(--redbg);border-color:#fbd9d4;color:var(--red)}
 .av{width:20px;height:20px;border-radius:50%;color:#fff;font-size:10px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;flex:none}
 /* posts */
 .post{border:1px solid var(--line);border-radius:11px;padding:11px 13px;margin-top:9px;font-size:13.5px;display:flex;gap:11px;background:#fff}
 .post .thumb{width:104px;height:66px;border-radius:8px;flex:none;background:#eef0f4 center/cover;position:relative;overflow:hidden}
 .post .thumb .play{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
 .post .body{flex:1;min-width:0}
 .post .who{font-size:12.5px;margin-bottom:3px;color:#48506a;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
 .post .txt{white-space:pre-wrap;word-break:break-word;color:var(--ink)}
 .post .eng{font-size:11.5px;color:var(--faint);margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;align-items:center}
 .post .eng a{font-weight:600;text-decoration:none}
 .evidence .post{background:var(--redbg);border-color:#fbd9d4}
 .relpill{font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:10px;background:#eef0f4;color:#48506a}
 /* narrative + media */
 .mcard{display:flex;gap:14px}.mcard .thumb{width:160px;height:96px;border-radius:9px;flex:none;background:#eef0f4 center/cover;position:relative;overflow:hidden}
 .tag{display:inline-flex;align-items:center;gap:5px;background:#f1f2f6;border:1px solid var(--line);color:#48506a;border-radius:14px;padding:2px 10px;font-size:11.5px;margin:4px 5px 0 0}
 .reach{height:8px;background:#eef0f4;border-radius:5px;overflow:hidden;margin:8px 0 4px;max-width:360px}
 .reach .f{height:100%;background:var(--brand);border-radius:5px}
 /* chart */
 .chart-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px}
 .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin:2px 0 4px}
 .legend span{display:inline-flex;align-items:center;gap:6px}
 .legend b{display:inline-block;width:10px;height:10px;border-radius:3px}
 /* timeline */
 .tl{border-left:2px solid var(--line);margin-left:9px;padding-left:18px}
 .tl .ev{position:relative;margin-bottom:14px}
 .tl .ev::before{content:"";position:absolute;left:-25px;top:3px;width:11px;height:11px;border-radius:50%;background:var(--brand);border:2.5px solid #fff;box-shadow:0 0 0 1px var(--line)}
 .tl .ev.coord::before{background:var(--red)}
 .tl .t{font-size:12px;color:var(--faint)}.tl .d{font-size:13.5px;margin-top:1px}
 .flow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 0}
 .flow .node{background:var(--brandbg);border:1px solid #dfe2fb;border-radius:10px;padding:6px 12px;font-size:12.5px;color:#2b2fa6;display:inline-flex;gap:7px;align-items:center}
 .flow .arr{color:var(--faint)}
 /* controls + downloads */
 .controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
 .controls select,.controls input{padding:9px 11px;border:1px solid var(--line);border-radius:9px;font-size:13px;background:#fff;color:var(--ink)}
 .count{font-size:12px;color:var(--muted);margin-left:auto}
 .dlcard{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin-bottom:34px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
 .dlcard .lbl{font-weight:650;font-size:13.5px;display:flex;align-items:center;gap:8px}
 .dlcard select{padding:9px 11px;border:1px solid var(--line);border-radius:9px;font-size:13px;background:#fff}
 .btn{padding:9px 14px;border:1px solid var(--line);background:#fff;border-radius:9px;font-size:13px;cursor:pointer;color:var(--brand);font-weight:650;display:inline-flex;gap:7px;align-items:center}
 .btn:hover{background:var(--brandbg)}
 .btn.primary{background:var(--brand);color:#fff;border-color:var(--brand)}.btn.primary:hover{background:#3236c2}
 .empty{color:var(--muted);font-size:13.5px;padding:10px 0}
 .nav{position:sticky;top:0;background:rgba(244,245,248,.92);backdrop-filter:blur(6px);z-index:9;display:flex;gap:4px;flex-wrap:wrap;padding:10px 0;margin-bottom:8px;border-bottom:1px solid var(--line)}
 .nav a{font-size:12.5px;color:var(--muted);text-decoration:none;padding:5px 10px;border-radius:8px;font-weight:600}
 .nav a:hover{background:#fff;color:var(--brand)}
 .foot{text-align:center;color:var(--faint);font-size:12px;margin-top:26px;line-height:1.7}
</style></head><body><div class="wrap">

<header class="top">
 <div class="eyebrow">Coordinated activity &amp; disinformation report</div>
 <h1 id="title"></h1>
 <div class="meta" id="hmeta"></div>
 <div id="hkw" style="margin-top:4px"></div>
</header>

<nav class="nav">
 <a href="#s-media">Media</a><a href="#s-narr">Narratives</a>
 <a href="#s-coord">Coordination</a><a href="#s-origin">Origin &amp; spread</a>
 <a href="#s-posts">Browse posts</a><a href="#s-download">Download</a>
</nav>

<div class="lede" id="lede"></div>

<details class="glossary"><summary><span id="gl-ic"></span> New to this report? Read how to understand it</summary>
 <div class="gl">
  <div><b>Incident</b> — the specific event, claim or video being investigated (not a broad topic).</div>
  <div><b>Relevant post</b> — a post we confirmed is actually about this incident. Unrelated or generic posts are set aside.</div>
  <div><b>Media cluster</b> — the same photo or video found on several accounts (a reupload or a copy).</div>
  <div><b>Narrative</b> — a group of posts making the same kind of claim or point.</div>
  <div><b>Coordinated group</b> — accounts that pushed the same media or message <i>together</i>, beyond coincidence.</div>
  <div><b>Confidence</b> — how sure we are (Low / Medium / High). Everything here is a lead for a human to review, not proof.</div>
 </div>
</details>

<div class="verdict" id="verdict"></div>
<div class="stats" id="stats"></div>
<div class="viz" id="viz"></div>

<!-- A. MEDIA -->
<div class="block" id="s-media">
 <div class="sec-h"><span class="tag">A</span><h2 class="sec">Media intelligence</h2></div>
 <p class="sec-desc">Is the same video or image being spread by multiple accounts? Each card below is one piece of media we saw on more than one account — a reupload or a copy. This is the strongest sign of an organised push.</p>
 <div id="media"></div>
</div>

<!-- B. NARRATIVES -->
<div class="block" id="s-narr">
 <div class="sec-h"><span class="tag">B</span><h2 class="sec">Narrative analysis</h2></div>
 <p class="sec-desc">The different things people are saying about this incident, grouped by the kind of claim they make, and how loud each one got over time.</p>
 <div class="chart-card">
  <h4 style="margin:0 0 2px">How loud each storyline got</h4>
  <div class="sub" style="color:var(--faint);font-size:12px;margin-bottom:6px">Number of posts per day, by narrative.</div>
  <div class="legend" id="lg"></div>
  <svg id="chart" viewBox="0 0 600 190"></svg>
 </div>
 <div id="narratives" style="margin-top:14px"></div>
</div>

<!-- C. COORDINATION -->
<div class="block" id="s-coord">
 <div class="sec-h"><span class="tag">C</span><h2 class="sec">Coordination analysis</h2></div>
 <p class="sec-desc">Groups of accounts that behaved as one — sharing the same video or posting the same message together. Posting at a similar time is <b>never</b> treated as coordination on its own; every group here shares real content, and each shows the evidence behind it.</p>
 <div id="groups"></div>
</div>

<!-- D. ORIGIN -->
<div class="block" id="s-origin">
 <div class="sec-h"><span class="tag">D</span><h2 class="sec">Origin &amp; spread</h2></div>
 <p class="sec-desc" id="origin-note"></p>
 <div id="earliest"></div>
 <h4 style="font-size:14px;margin:16px 0 8px">What happened, in order</h4>
 <div class="tl" id="timeline"></div>
 <h4 style="font-size:14px;margin:20px 0 8px">How each storyline moved between platforms</h4>
 <div id="spread"></div>
</div>

<!-- E. POSTS -->
<div class="block" id="s-posts">
 <div class="sec-h"><span class="tag">E</span><h2 class="sec">Browse the posts</h2></div>
 <p class="sec-desc">Every post we confirmed is about this incident. Filter by platform, storyline, or search the text.</p>
 <div class="controls">
  <label>Platform <select id="f-plat"></select></label>
  <label>Narrative <select id="f-narr"></select></label>
  <label style="display:inline-flex;gap:6px;align-items:center"><input type="checkbox" id="f-coord"> coordinated only</label>
  <input type="search" id="f-q" placeholder="search text…" style="min-width:160px">
  <span class="count" id="f-count"></span>
 </div>
 <div id="feed"></div>
</div>

<!-- DOWNLOAD -->
<div class="dlcard" id="s-download">
 <span class="lbl" id="dl-ic">Download the data</span>
 <select id="dl-set">
  <option value="report">Full report</option>
  <option value="posts">Posts</option>
  <option value="groups">Coordinated groups</option>
  <option value="media">Media clusters</option>
  <option value="narratives">Narratives</option>
  <option value="timeline">Timeline</option>
 </select>
 <button class="btn primary" id="dl-json">Download JSON</button>
 <button class="btn" id="dl-csv">Download CSV</button>
 <span style="font-size:12px;color:var(--faint)" id="dl-note"></span>
</div>

<div class="foot" id="foot"></div>
</div>

<script>
const D = /*__DATA__*/;
const PAL=['#3d42d6','#f59e0b','#10b981','#e11d48','#0ea5e9','#8b5cf6','#84cc16','#ef6820'];
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num=n=>{n=n||0;return n>=1e6?(n/1e6).toFixed(1)+'M':n>=1000?(n/1000).toFixed(n>=1e4?0:1)+'k':''+n;};
const when=t=>(t||'').replace('T',' ').slice(0,16);
const ACC=D.accounts||{};
const nameOf=id=>{const a=ACC[id];return a&&a.name?a.name:(id||'').split(':').pop();};

/* ---- inline SVG icons (consistent across every OS) ---- */
const IC={
 yt:'<svg width="15" height="15" viewBox="0 0 24 24"><rect x="1" y="4" width="22" height="16" rx="4.5" fill="#ff0000"/><path d="M10 8.5l6 3.5-6 3.5z" fill="#fff"/></svg>',
 tg:'<svg width="15" height="15" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#2aabee"/><path d="M5.5 11.8l12-4.6c.6-.2 1.1.1.9.9l-2 9.4c-.1.6-.5.7-1 .4l-2.8-2.1-1.4 1.3c-.2.2-.3.3-.6.3l.2-3 5.2-4.7c.2-.2 0-.3-.3-.1l-6.4 4-2.8-.9c-.6-.2-.6-.6.1-.9z" fill="#fff"/></svg>',
 check:'<svg width="22" height="22" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#067a4d"/><path d="M7 12.5l3 3 7-7" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 flag:'<svg width="22" height="22" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#d92d20"/><path d="M8 6v12M8 7h7l-1.3 2.5L15 12H8" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 warn:'<svg width="22" height="22" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#b54708"/><path d="M12 7v6M12 16.2v.2" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/></svg>',
 book:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3d42d6" stroke-width="1.8"><path d="M4 5.5A2 2 0 016 4h5v15H6a2 2 0 00-2 1V5.5zM20 5.5A2 2 0 0018 4h-5v15h5a2 2 0 012 1V5.5z"/></svg>',
 dl:'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0l-4-4m4 4l4-4M5 19h14" stroke-linecap="round" stroke-linejoin="round"/></svg>',
 play:'<svg width="22" height="22" viewBox="0 0 24 24"><circle cx="12" cy="12" r="12" fill="rgba(0,0,0,.45)"/><path d="M10 8l6 4-6 4z" fill="#fff"/></svg>',
 eye:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="2.5"/></svg>',
 like:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 10v10M7 10l4-7a2 2 0 013 2l-1 5h5a2 2 0 012 2.3l-1.3 6A2 2 0 0117.7 20H7"/></svg>',
 share:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 12v7a1 1 0 001 1h14a1 1 0 001-1v-7M16 6l-4-4-4 4M12 2v14"/></svg>',
 chat:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12a8 8 0 01-11.6 7.1L3 21l1.9-6.4A8 8 0 1121 12z"/></svg>',
};
const plat=p=>IC[p==='youtube'?'yt':'tg']||'';
const platName=p=>p==='youtube'?'YouTube':(p==='telegram'?'Telegram':p);

/* plain-language dictionaries */
const DET={
 shared_media:['Shared the same video/image','The exact same clip or picture was posted by these accounts.'],
 near_dup_caption:['Near-identical captions','They wrote the same message, word for word or nearly.'],
 sync_dissemination:['Posted in sync','They repeatedly posted the same content within minutes of each other.'],
 cross_platform:['Spread across platforms','The same content showed up on both YouTube and Telegram.'],
 amplification:['Amplified each other','They forwarded or replied to boost the same posts.'],
 account_similarity:['Similar accounts','Created around the same time, similar names or reused photos (a supporting hint only).'],
};
const NARR={
 'Potential misinformation':'Sensational, unverified claims that may be false.',
 'Unverified claim':'A specific claim with no supporting evidence yet.',
 'Contradictory claim':'Conflicting versions of what happened.',
 'Debunking content':'Posts pushing back — calling the content fake, old or AI-made.',
 'Verified information':'Posts backed by reputable news sources.',
 'General discussion':'Ordinary conversation about the topic — no specific claim.',
};
const MATCH={exact_file:'identical file',keyframes:'identical video frames',
 image_similar:'visually identical image',thumbnail_similar:'similar thumbnail only'};

function avatar(id){const nm=nameOf(id);let h=0;for(let i=0;i<id.length;i++)h=(h*31+id.charCodeAt(i))|0;
 const c=PAL[Math.abs(h)%PAL.length];const i=(nm.match(/[A-Za-z0-9]/)||['?'])[0].toUpperCase();
 return `<span class="av" style="background:${c}">${i}</span>`;}
function meter(level){const l={High:3,Medium:2,Low:1}[level]||1;
 return `<span class="meter l${l}"><i></i><i></i><i></i></span>`;}

function postCard(p){
 const bg=p.thumb?`style="background-image:url('${esc(p.thumb)}')"`:'';
 const thumb=(p.thumb||p.has_video)?`<div class="thumb" ${bg}>${p.has_video?`<span class="play">${IC.play}</span>`:''}</div>`:'';
 const co=p.coordinated?`<span class="badge b-red" style="font-size:10px;padding:1px 7px">coordinated</span>`:'';
 const mc=(p.media_cluster!=null&&p.media_cluster!=='')?`<span class="tag" style="margin:0">media #${p.media_cluster}</span>`:'';
 const link=p.url?`<a href="${esc(p.url)}" target="_blank" rel="noopener">open ↗</a>`:'';
 const eng=[];
 if(p.views)eng.push(`${IC.eye} ${num(p.views)}`);
 if(p.likes)eng.push(`${IC.like} ${num(p.likes)}`);
 if(p.shares)eng.push(`${IC.share} ${num(p.shares)}`);
 if(p.replies)eng.push(`${IC.chat} ${num(p.replies)}`);
 return `<div class="post">${thumb}<div class="body">
  <div class="who">${plat(p.platform)} <b>${esc(nameOf(p.account_id))}</b>
   <span style="color:var(--faint)">· ${esc(p.kind)} · ${when(p.timestamp)}</span>
   <span class="relpill" title="How strongly this matches the incident">match ${p.relevance_score}</span> ${co} ${mc}</div>
  <div class="txt">${esc(p.text)}</div>
  <div class="eng">${eng.join('<span style="color:#d7dbe4">·</span>')} ${link}</div>
 </div></div>`;
}

/* ---------- header ---------- */
document.getElementById('title').textContent=D.meta.incident;
document.getElementById('hmeta').innerHTML=
 `<span><b style="color:var(--ink)">Keyword:</b> ${esc(D.meta.primary_keyword)}</span>`
 +`<span>${D.meta.date_start} → ${D.meta.date_end}</span>`
 +(D.meta.platforms||[]).map(p=>`<span class="pill">${plat(p)} ${platName(p)}</span>`).join('');
document.getElementById('hkw').innerHTML=(D.meta.keywords||[]).map(k=>`<span class="kw">${esc(k)}</span>`).join('');
document.getElementById('gl-ic').innerHTML=IC.book;
document.getElementById('dl-ic').innerHTML=IC.dl+' Download the data';

/* ---------- plain-English summary ---------- */
const S=D.summary;
(function(){
 const r=D.risk;
 const verdict=r.level==='High'?'we found signs of a coordinated push':
   (r.level==='Medium'?'we found only weak, likely-organic signals':'we found no coordinated push');
 document.getElementById('lede').innerHTML=
  `We examined <b>${num(S.total_collected)}</b> posts mentioning “${esc(D.meta.primary_keyword)}” on `
  +`${(D.meta.platforms||[]).map(platName).join(' and ')}. `
  +`<b>${num(S.relevant_posts)}</b> were actually about this incident — the rest were generic comments or unrelated content, so we set them aside. `
  +`Among the relevant posts we found <b>${S.num_media_clusters}</b> reused video/image${S.num_media_clusters===1?'':'s'}, `
  +`<b>${S.num_narratives}</b> distinct storyline${S.num_narratives===1?'':'s'}, and overall <b>${verdict}</b>.`;
})();

/* ---------- verdict ---------- */
const r=D.risk, vic={High:IC.flag,Medium:IC.warn,None:IC.check}[r.level]||IC.check;
document.getElementById('verdict').className='verdict '+r.level;
document.getElementById('verdict').innerHTML=`<div class="ic">${vic}</div><div><h2>${esc(r.headline)}</h2><p>${esc(r.explain)}</p></div>`;

/* ---------- stat tiles ---------- */
document.getElementById('stats').innerHTML=[
 ['Relevant posts',num(S.relevant_posts)],['YouTube',num(S.youtube_posts)],['Telegram',num(S.telegram_posts)],
 ['Accounts',num(S.unique_accounts)],['Reused media',S.num_media_clusters],['Storylines',S.num_narratives],
 ['Coordinated groups',S.num_strong_groups+S.num_possible_groups,S.num_strong_groups? 'flag':''],
 ['Flagged accounts',S.flagged_accounts,S.flagged_accounts?'flag':'ok']]
 .map(t=>`<div class="stat ${t[2]||''}"><div class="n">${t[1]}</div><div class="l">${t[0]}</div></div>`).join('');

/* ---------- viz: relevance funnel + platform split ---------- */
(function(){
 const rel=S.relevance||{}, tot=rel.total||1;
 const seg=[['Relevant',rel.relevant,'#10b981'],['Needs review',rel.review,'#f59e0b'],
  ['Set aside',rel.irrelevant,'#cdd2dd']];
 const bar=seg.map(s=>`<div class="seg" style="width:${100*(s[1]||0)/tot}%;background:${s[2]}" title="${s[0]}: ${s[1]}"></div>`).join('');
 const rows=seg.map(s=>`<span class="row"><span class="sw" style="background:${s[2]}"></span>${s[0]}: <b style="color:var(--ink);margin-left:3px">${num(s[1]||0)}</b></span>`).join('');
 const plats=Object.entries((function(){const o={};(D.posts||[]).forEach(p=>o[p.platform]=(o[p.platform]||0)+1);return o;})());
 const pmax=Math.max(1,...plats.map(p=>p[1]));
 const split=plats.map(([p,c],i)=>`<div class="b"><span style="width:76px;display:inline-flex;gap:6px;align-items:center">${plat(p)} ${platName(p)}</span>
   <span class="track"><span class="fill" style="width:${100*c/pmax}%;background:${PAL[i]}"></span></span><b>${num(c)}</b></div>`).join('');
 document.getElementById('viz').innerHTML=
  `<div class="panel funnel"><h4>What we kept, and what we set aside</h4>
    <p class="sub">Most collected posts aren't about the incident. We only analyse the relevant ones.</p>
    <div class="bar">${bar}</div><div style="display:flex;gap:16px;flex-wrap:wrap">${rows}</div>
    <div class="row" style="margin-top:10px;color:var(--faint)">${num(rel.generic||0)} of the set-aside posts were generic comments (“first”, “nice video”).</div></div>
   <div class="panel split"><h4>Where the relevant posts came from</h4>
    <p class="sub">Relevant posts by platform.</p>${split||'<div class="empty">No relevant posts.</div>'}</div>`;
})();

/* ---------- A. media ---------- */
document.getElementById('media').innerHTML=(D.media_clusters||[]).map(c=>{
 const cf=c.confidence==='high'?'b-red':(c.confidence==='medium'?'b-amber':'b-gray');
 const lvl=c.confidence==='high'?'High':(c.confidence==='medium'?'Medium':'Low');
 const bg=c.thumb?`style="background-image:url('${esc(c.thumb)}')"`:'';
 const how=(c.match_types||[]).map(m=>MATCH[m]||m).join(', ');
 const reach=Math.min(100,(c.num_accounts||1)*20);
 return `<div class="card"><div class="mcard">
  <div class="thumb" ${bg}><span class="play">${IC.play}</span></div><div style="flex:1;min-width:0">
   <div><span class="badge ${cf}">${lvl} confidence ${meter(lvl)}</span>
    <b style="margin-left:8px">Reused media #${c.cluster_id}</b></div>
   <div class="whatis"><b>What this is:</b> the same media (${esc(how)}) appeared on
    <b>${c.num_accounts}</b> account${c.num_accounts===1?'':'s'} across ${(c.platforms||[]).map(platName).join(' &amp; ')}.
    ${(c.match_types||[]).includes('thumbnail_similar')&&!(c.match_types||[]).some(m=>m==='exact_file'||m==='keyframes')?'Only the thumbnail matched, so this is a weaker signal — not proof the full videos are identical.':''}</div>
   <div class="reach"><div class="f" style="width:${reach}%"></div></div>
   <div>${(c.platforms||[]).map(p=>`<span class="tag">${plat(p)} ${platName(p)}</span>`).join('')}
    <span class="tag">${c.num_accounts} accounts</span><span class="tag">first seen ${when(c.first_observed)}</span></div>
  </div></div></div>`;
}).join('')||`<div class="card"><div class="whatis" style="margin:0"><b>Nothing to show here.</b> No single video or image was found being shared across multiple accounts. For a real incident built around a specific clip, this section shows every account that reposted it.</div></div>`;

/* ---------- B. narratives chart + cards ---------- */
(function(){const svg=document.getElementById('chart'),W=600,H=190,pad=34;const ns=D.narratives||[];
 const days=[...new Set(ns.flatMap(n=>Object.keys(n.volume_over_time||{})))].sort();
 if(!days.length){svg.innerHTML=`<text x="20" y="40" fill="#8a93a6" font-size="13">Not enough dated posts to chart.</text>`;return;}
 const x=i=>pad+i*(W-pad-12)/Math.max(1,days.length-1);
 let max=1;ns.forEach(n=>days.forEach(d=>max=Math.max(max,(n.volume_over_time||{})[d]||0)));
 const y=v=>H-26-v*(H-42)/max;
 let o=`<line x1="${pad}" y1="${H-26}" x2="${W-6}" y2="${H-26}" stroke="#e7eaf0"/>`;
 o+=`<text x="4" y="${y(max)+4}" fill="#8a93a6" font-size="9">${max}</text>`;
 days.forEach((d,i)=>{if(i%Math.ceil(days.length/7||1)===0)o+=`<text x="${x(i)}" y="${H-10}" fill="#8a93a6" font-size="9" text-anchor="middle">${d.slice(5)}</text>`;});
 ns.slice(0,8).forEach((n,ni)=>{const pts=days.map((d,i)=>`${x(i)},${y((n.volume_over_time||{})[d]||0)}`).join(' ');
  o+=`<polyline points="${pts}" fill="none" stroke="${PAL[ni%PAL.length]}" stroke-width="2.4" stroke-linejoin="round"/>`;});
 svg.innerHTML=o;
 document.getElementById('lg').innerHTML=ns.slice(0,8).map((n,ni)=>
  `<span><b style="background:${PAL[ni%PAL.length]}"></b>${esc(n.label)}</span>`).join('');
})();
const STB={debunking:'b-green',questioning:'b-blue',asserting:'b-amber',reporting:'b-green',discussion:'b-gray'};
document.getElementById('narratives').innerHTML=(D.narratives||[]).map(n=>{
 const plats=Object.entries(n.platform_breakdown||n.volume_per_platform||{});
 const mc=(n.media_cluster_ids||[]).map(id=>`<span class="tag">media #${id}</span>`).join('');
 const ex=(n.examples||[]).slice(0,2).map(postCard).join('');
 return `<div class="card">
  <div><span class="badge ${STB[n.stance]||'b-gray'}">${esc(n.label)}</span>
   <b style="margin-left:8px">${esc(n.claim_summary||n.label)}</b></div>
  <div class="whatis"><b>What this is:</b> ${esc(NARR[n.label]||'a group of related posts.')}
   ${n.coordinated_share>0?` <b>${Math.round(n.coordinated_share*100)}%</b> of these posts come from flagged accounts.`:''}</div>
  <div style="font-size:12.5px;color:var(--muted)">${n.size} posts · ${n.unique_accounts} accounts · leaning: ${esc(n.stance)}</div>
  <div style="margin-top:4px">${plats.map(([p,c])=>`<span class="tag">${plat(p)} ${platName(p)}: ${c}</span>`).join('')} ${mc}</div>
  ${ex?`<details class="more"><summary>Show example posts</summary>${ex}</details>`:''}</div>`;
}).join('')||'<div class="empty">No storylines met the minimum size.</div>';

/* ---------- C. coordination ---------- */
document.getElementById('groups').innerHTML=(D.groups||[]).filter(g=>g.classification!=='insufficient evidence').map(g=>{
 const strong=g.classification.startsWith('strong');
 const sigs=(g.detectors||[]).map(d=>`<span class="sig" title="${esc((DET[d]||['',''])[1])}">✓ ${esc((DET[d]||[d])[0])}</span>`).join('');
 const members=g.account_ids.map(a=>`<span class="chip coord">${avatar(a)}${plat((ACC[a]||{}).platform)} ${esc(nameOf(a))}</span>`).join('');
 const ev=(g.example_posts||[]).slice(0,6).map(postCard).join('');
 const plainWhy=strong
   ? `These <b>${g.account_ids.length}</b> accounts didn't just talk about the same thing — they pushed the <b>same video or message together</b>. That pattern is what flags them.`
   : `These <b>${g.account_ids.length}</b> accounts show <b>weak hints</b> of acting together (timing or amplification), but with no shared video or identical message to confirm it. Likely coincidental.`;
 return `<div class="card ${strong?'hi':'med'}">
  <div><span class="badge ${strong?'b-red':'b-amber'}">${strong?'Likely coordinated':'Possible — weak'}</span>
   <span class="badge b-gray" style="margin-left:6px">${g.confidence} confidence ${meter(g.confidence)}</span>
   <b style="margin-left:8px">${g.account_ids.length} accounts</b></div>
  <div class="whatis"><b>What this means:</b> ${plainWhy}</div>
  <div style="font-size:12.5px;color:var(--muted)">How we're sure: ${esc(g.confidence_explain||'')}</div>
  <div class="sigs">${sigs}</div>
  <details class="more" open><summary>See the evidence</summary>
   <ul class="trail">${(g._detail_lines||[]).map(l=>`<li>${esc(l)}</li>`).join('')}</ul></details>
  ${ev?`<details class="more"><summary>See their posts side by side</summary><div class="evidence">${ev}</div></details>`:''}
  <details class="more"><summary>List all ${g.account_ids.length} accounts</summary><div class="chips">${members}</div></details>
 </div>`;
}).join('')||`<div class="card"><div style="display:flex;gap:12px;align-items:flex-start"><div>${IC.check}</div>
  <div><b style="font-size:15px">No coordinated groups found.</b>
  <div class="whatis" style="margin-top:8px"><b>What this means:</b> we checked every pair of accounts for shared videos, identical messages, synchronized posting, cross-platform spread and amplification — and none of it lined up. Posting at a similar time, on its own, was never counted. For a broad topic this is the expected, correct result.</div></div></div></div>`;

/* ---------- D. origin ---------- */
document.getElementById('origin-note').textContent=(D.propagation||{}).note||'';
(function(){const e=(D.propagation||{}).earliest||{};const o=e.overall;
 document.getElementById('earliest').innerHTML=o?`<div class="card"><b>Earliest post we observed:</b>
  <span style="display:inline-flex;gap:6px;align-items:center;margin-left:4px">${plat(o.platform)} ${esc(nameOf(o.account_id))}</span>
  <span style="color:var(--faint)"> · ${when(o.timestamp)}</span> ${o.url?`<a href="${esc(o.url)}" target="_blank" rel="noopener">open ↗</a>`:''}
  <div class="whatis" style="margin-bottom:0"><b>Note:</b> this is the earliest post we <i>collected</i> — it may itself be a reupload, not the true original source.</div>
  <div style="font-size:13px;margin-top:8px">“${esc(o.text)}”</div></div>`:'';
})();
document.getElementById('timeline').innerHTML=((D.propagation||{}).timeline||[]).map(ev=>
 `<div class="ev ${ev.coordinated?'coord':''}"><div class="t">${when(ev.timestamp)} · ${plat(ev.platform)} ${esc(nameOf(ev.account_id))}</div>
  <div class="d"><b>${esc(ev.event)}</b>${ev.text?` — ${esc((ev.text||'').slice(0,110))}`:''} ${ev.url?`<a href="${esc(ev.url)}" target="_blank" rel="noopener">↗</a>`:''}</div></div>`).join('')
 ||'<div class="empty">Not enough data to build a timeline.</div>';
document.getElementById('spread').innerHTML=((D.propagation||{}).per_narrative||[]).slice(0,6).map(s=>{
 const path=(s.spread_path||[]).map(p=>`<span class="node">${plat(p.platform)} ${platName(p.platform)} <span style="color:var(--faint)">${when(p.first_seen)}</span></span>`).join('<span class="arr">→</span>');
 return `<div class="card" style="padding:14px 18px"><b>${esc(s.summary||s.label)}</b>
  ${s.coordinated_share>0.3?`<span class="badge b-red" style="margin-left:6px">${Math.round(s.coordinated_share*100)}% flagged</span>`:''}
  <div class="flow">${path||'<span class="empty">single platform</span>'}</div></div>`;
}).join('')||'<div class="empty">—</div>';

/* ---------- E. browse ---------- */
(function(){const plats=[...new Set((D.posts||[]).map(p=>p.platform))];
 const fp=document.getElementById('f-plat'),fn=document.getElementById('f-narr');
 fp.innerHTML='<option value="">All platforms</option>'+plats.map(p=>`<option value="${p}">${platName(p)}</option>`).join('');
 fn.innerHTML='<option value="">All storylines</option>'+(D.narratives||[]).map(n=>`<option value="${n.narrative_id}">${esc(n.label)} #${n.narrative_id}</option>`).join('');
 const feed=document.getElementById('feed'),cnt=document.getElementById('f-count');
 function render(){const vp=fp.value,vn=fn.value,vc=document.getElementById('f-coord').checked,vq=document.getElementById('f-q').value.toLowerCase();
  let rows=(D.posts||[]).filter(p=>(!vp||p.platform===vp)&&(vn===''||String(p.narrative_id)===vn)&&(!vc||p.coordinated)&&(!vq||(p.text||'').toLowerCase().includes(vq)));
  cnt.textContent=rows.length+' posts';feed.innerHTML=rows.slice(0,200).map(postCard).join('')||'<div class="empty">No matching posts.</div>';}
 ['f-plat','f-narr','f-coord','f-q'].forEach(id=>document.getElementById(id).addEventListener('input',render));render();})();

/* ---------- downloads (JSON + CSV) ---------- */
function dl(name,content,mime){const b=new Blob([content],{type:mime});const u=URL.createObjectURL(b);
 const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1500);}
function toCSV(rows,cols){const q=v=>{v=v==null?'':Array.isArray(v)?v.join('|'):String(v);
 return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
 return cols.join(',')+'\n'+rows.map(r=>cols.map(c=>q(r[c])).join(',')).join('\n');}
const DS={
 report:{json:()=>D,csv:null,file:'casmd_report'},
 posts:{json:()=>D.posts,file:'casmd_posts',
  cols:['post_id','platform','kind','account_id','timestamp','relevance_score','relevance_decision','coordinated','narrative_id','media_cluster','likes','shares','replies','views','url','text']},
 groups:{json:()=>D.groups,file:'casmd_coordinated_groups',
  rows:()=> (D.groups||[]).map(g=>({group_id:g.group_id,classification:g.classification,confidence:g.confidence,
   num_accounts:g.account_ids.length,score:g.score,detectors:g.detectors,account_ids:g.account_ids,evidence:g.confidence_explain})),
  cols:['group_id','classification','confidence','num_accounts','score','detectors','account_ids','evidence']},
 media:{json:()=>D.media_clusters,file:'casmd_media_clusters',
  rows:()=>(D.media_clusters||[]).map(c=>({cluster_id:c.cluster_id,confidence:c.confidence,match_types:c.match_types,
   platforms:c.platforms,num_accounts:c.num_accounts,num_posts:c.num_posts,first_observed:c.first_observed,evidence:c.evidence})),
  cols:['cluster_id','confidence','match_types','platforms','num_accounts','num_posts','first_observed','evidence']},
 narratives:{json:()=>D.narratives,file:'casmd_narratives',
  rows:()=>(D.narratives||[]).map(n=>({narrative_id:n.narrative_id,label:n.label,stance:n.stance,size:n.size,
   unique_accounts:n.unique_accounts,media_clusters:n.media_cluster_ids,summary:n.claim_summary})),
  cols:['narrative_id','label','stance','size','unique_accounts','media_clusters','summary']},
 timeline:{json:()=>(D.propagation||{}).timeline,file:'casmd_timeline',
  rows:()=>((D.propagation||{}).timeline||[]).map(e=>({timestamp:e.timestamp,platform:e.platform,account:nameOf(e.account_id),
   event:e.event,coordinated:e.coordinated,text:e.text,url:e.url})),
  cols:['timestamp','platform','account','event','coordinated','text','url']},
};
function curSet(){return DS[document.getElementById('dl-set').value];}
function updNote(){const s=document.getElementById('dl-set').value;
 document.getElementById('dl-note').textContent=s==='report'?'(the full report is JSON only)':'';
 document.getElementById('dl-csv').style.opacity=s==='report'?.4:1;}
document.getElementById('dl-set').addEventListener('change',updNote);updNote();
document.getElementById('dl-json').onclick=()=>{const s=curSet();dl(s.file+'.json',JSON.stringify(s.json(),null,2),'application/json');};
document.getElementById('dl-csv').onclick=()=>{const s=curSet();if(!s.cols)return;
 const rows=s.rows?s.rows():s.json();dl(s.file+'.csv',toCSV(rows||[],s.cols),'text/csv');};

document.getElementById('foot').innerHTML='CASMD — Coordinated Activity &amp; Disinformation Detection.<br>Findings are leads for human review, not proof. “Earliest observed” is not necessarily the original source.';
</script></body></html>"""
