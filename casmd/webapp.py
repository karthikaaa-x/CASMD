"""
CASMD web UI — run an incident scan from the browser instead of the terminal.

    pip install flask
    python -m casmd.webapp            # open http://127.0.0.1:8000

The form collects the incident (name, keyword(s), optional description, date
range), the platforms, API keys, Telegram channels, and an optional Telegram
search-bot (near-global search). It runs the exact same incident-centric pipeline
as the CLI and then shows the generated dashboard. Keys you type are used only for
that run (set as environment variables in this local process) and are never
stored or sent anywhere except the platform APIs themselves.
"""

from __future__ import annotations

import os
import traceback

from .config import Config, Incident
from . import run as runner

try:
    from flask import Flask, request, redirect, send_file, Response
except ImportError:
    raise SystemExit("Flask not installed. Run:  pip install flask")

app = Flask(__name__)

# The detectors the current (incident-centric) pipeline runs — shown on the form
# so the operator sees exactly what will be evaluated.
DETECTORS = [
    ("Incident relevance", "Every post is scored against the incident (keywords + "
     "semantics); only relevant content is admitted. Generic comments and "
     "unrelated videos are excluded; YouTube comments need a relevant parent video."),
    ("Media correlation", "SHA-256 exact-file, video keyframe hashing and "
     "thumbnail perceptual hashing group reuploaded / modified copies into media "
     "clusters across both platforms."),
    ("Shared media", "Accounts posting the same / near-identical media."),
    ("Near-identical captions", "Accounts posting the same incident claims "
     "(generic phrases excluded)."),
    ("Synchronized dissemination", "Repeatedly posting the same media/narrative in "
     "a short window — counted ONLY when content is shared, never time alone."),
    ("Cross-platform propagation", "The same media/caption appearing on YouTube "
     "and Telegram."),
    ("Amplification", "Telegram forwards, repeated forwarding, YouTube reply chains."),
    ("Account similarity", "Creation bursts, reused avatars, similar handles, "
     "shared links — SUPPORTING signals only, never sufficient alone."),
]

PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CASMD — run an incident scan</title>
<style>
 body{margin:0;background:#f6f7f9;color:#121826;font:15px/1.6 -apple-system,Segoe UI,Roboto,Arial,sans-serif}
 .wrap{max-width:860px;margin:0 auto;padding:30px 20px 60px}
 h1{font-size:24px;margin:0 0 4px}.sub{color:#667085;margin:0 0 20px;font-size:14px}
 .grid{display:grid;grid-template-columns:1fr;gap:18px}
 @media(min-width:820px){.grid{grid-template-columns:1.4fr 1fr}}
 .card{background:#fff;border:1px solid #e6e9ef;border-radius:14px;padding:22px}
 label{display:block;font-weight:600;font-size:13px;margin:14px 0 5px}
 label:first-child{margin-top:0}
 input,select,textarea{width:100%;padding:10px 12px;border:1px solid #e6e9ef;border-radius:9px;font-size:14px;font-family:inherit}
 .row{display:flex;gap:14px}.row>div{flex:1}
 .checks{display:flex;gap:18px;margin-top:6px;flex-wrap:wrap}.checks label{display:flex;align-items:center;gap:6px;font-weight:500;margin:0}.checks input{width:auto}
 fieldset{border:1px solid #e6e9ef;border-radius:11px;margin:16px 0 0;padding:10px 16px 16px}
 legend{font-size:12px;color:#667085;padding:0 6px;font-weight:600}
 button{margin-top:20px;background:#3538cd;color:#fff;border:0;border-radius:10px;padding:13px 22px;font-size:15px;font-weight:650;cursor:pointer;width:100%}
 button:hover{background:#2a2ca8}
 .note{background:#eef0fe;border-radius:9px;padding:10px 13px;font-size:12.5px;color:#312e81;margin-top:14px}
 .warn{background:#fffaeb;color:#7a2e0e;border-radius:9px;padding:10px 13px;font-size:12.5px;margin-top:10px}
 .tabs{display:flex;gap:8px;margin:0 0 16px}.tabs a{padding:8px 14px;border:1px solid #e6e9ef;border-radius:9px;text-decoration:none;color:#3538cd;font-weight:600;font-size:13px;background:#fff}
 .det h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#667085;margin:0 0 10px}
 .det .d{margin-bottom:12px}.det .d b{font-size:13.5px}.det .d p{margin:2px 0 0;font-size:12.5px;color:#475467}
 .pipe{font-size:12px;color:#667085;margin-top:6px}
</style></head><body><div class="wrap">
 <h1>CASMD — run an incident scan</h1>
 <p class="sub">Incident-centric coordinated-dissemination detection · YouTube + Telegram</p>
 __MSG__
 <div class="tabs"><a href="/view">View last dashboard →</a></div>
 <div class="grid">
 <form method="post" action="/run" class="card">
  <label>Mode</label>
  <select name="mode" onchange="document.getElementById('live').style.display=this.value=='live'?'block':'none'">
   <option value="live">Live — collect real data (needs API keys)</option>
   <option value="demo">Demo — synthetic ship-bombing incident (no keys)</option></select>

  <label>Incident name</label>
  <input name="incident" placeholder="e.g. Acme Bank collapse rumor" value="">
  <label>Keyword(s) — a person, entity, bank, or phrase <span style="font-weight:400;color:#667085">(required)</span></label>
  <input name="primary" placeholder="e.g. Acme Bank" value="">
  <label>Additional keywords (comma-separated, optional)</label>
  <input name="keywords" placeholder="e.g. Acme Bank fraud, Acme withdrawal, AcmeBank scam">
  <label>Description (optional)</label>
  <textarea name="description" rows="2" placeholder="Optional context — leave blank if you just have keywords"></textarea>
  <div class="row"><div><label>From</label><input type="date" name="start"></div>
   <div><label>To</label><input type="date" name="end"></div></div>
  <div class="pipe">Leave dates blank on a live run to use the last 14 days.</div>

  <div id="live">
   <label>Platforms</label>
   <div class="checks">
    <label><input type="checkbox" name="platforms" value="youtube" checked> YouTube</label>
    <label><input type="checkbox" name="platforms" value="telegram" checked> Telegram</label></div>

   <fieldset><legend>API keys (used only for this run, never stored)</legend>
    <label>YouTube Data API key</label><input name="YT_API_KEY" placeholder="AIza…">
    <div class="row"><div><label>Telegram API ID</label><input name="TG_API_ID" placeholder="1234567"></div>
     <div><label>Telegram API hash</label><input name="TG_API_HASH" placeholder="32-char hash"></div></div>
    <label>Telegram channels (optional, comma-separated — blank = global search)</label>
    <input name="channels" placeholder="channel1,channel2">
    <div class="checks" style="margin-top:8px"><label><input type="checkbox" name="tg_all"> pull ALL messages from those channels (ignore keyword)</label></div>
   </fieldset>

   <fieldset><legend>Telegram search bot — near-global search (advanced, higher risk)</legend>
    <div class="checks"><label><input type="checkbox" name="nicegram"> drive a Telegram search bot via my account for near-global search</label></div>
    <label>Bot @username</label><input name="NICEGRAM_BOT" placeholder="@SomeSearchBot">
    <div class="warn">Automating your account against a bot can get it rate-limited or banned. Use a burner account, not your main.</div>
   </fieldset>
  </div>

  <div class="note">Keys stay in this local process for the run and are sent only to the platform's own API. The app runs on your machine.</div>
  <button type="submit">Run scan →</button>
 </form>

 <div class="card det">
  <h3>What this scan runs</h3>
  __DETECTORS__
 </div>
 </div>
</div></body></html>"""


def _render(msg=""):
    dets = "".join(
        f'<div class="d"><b>{i+1}. {t}</b><p>{d}</p></div>'
        for i, (t, d) in enumerate(DETECTORS))
    return (PAGE.replace("__MSG__", f'<div class="warn">{msg}</div>' if msg else "")
                .replace("__DETECTORS__", dets))


@app.route("/")
def index():
    return _render()


@app.route("/run", methods=["POST"])
def do_run():
    f = request.form
    mode = f.get("mode", "live")
    if not (f.get("primary") or mode == "demo"):
        return Response(_render("Enter at least one keyword."), mimetype="text/html")
    if mode == "demo":
        # Synthetic data is the fixed ship-bombing incident; use its defaults so
        # the date filter admits it (matches `python -m casmd.run --demo`).
        inc = Incident(**{**runner.DEMO_INCIDENT.__dict__})
    else:
        plats = tuple(f.getlist("platforms")) or ("youtube", "telegram")
        inc = Incident(
            name=f.get("incident") or (f.get("primary") or "Untitled incident"),
            primary_keyword=f.get("primary") or "",
            additional_keywords=[k.strip() for k in f.get("keywords", "").split(",") if k.strip()],
            description=f.get("description") or "",
            date_start=f.get("start") or Incident.date_start,
            date_end=f.get("end") or Incident.date_end,
            platforms=plats)
        # live with no dates -> last 14 days
        if not (f.get("start") and f.get("end")):
            from datetime import date, timedelta
            inc.date_end = date.today().isoformat()
            inc.date_start = (date.today() - timedelta(days=14)).isoformat()
    cfg = Config(incident=inc)
    for k in ("YT_API_KEY", "TG_API_ID", "TG_API_HASH", "NICEGRAM_BOT"):
        if f.get(k):
            os.environ[k] = f[k].strip()
    channels = [c.strip() for c in f.get("channels", "").split(",") if c.strip()] or None
    try:
        if mode == "demo":
            runner.run(cfg, reseed=True)
        else:
            runner.run(cfg, reseed=False, live=True, tg_channels=channels,
                       tg_search=(f.get("tg_all") != "on"),
                       nicegram=(f.get("nicegram") == "on"),
                       nicegram_bot=f.get("NICEGRAM_BOT") or None)
    except SystemExit as e:
        return Response(_render(f"Run stopped: {e}"), mimetype="text/html")
    except Exception:
        return Response(_render("<pre style='white-space:pre-wrap'>Error:\n"
                                + traceback.format_exc() + "</pre>"),
                        mimetype="text/html")
    return redirect("/view")


@app.route("/view")
def view():
    path = os.path.abspath(os.path.join(Config().out_dir, "dashboard.html"))
    if not os.path.exists(path):
        return Response(_render("No dashboard yet — run a scan first."),
                        mimetype="text/html")
    return send_file(path)


def main():
    port = int(os.environ.get("CASMD_PORT", "8000"))
    url = f"http://127.0.0.1:{port}"
    print(f"\n  CASMD web UI running → open {url}\n")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    app.run(port=port, debug=False)


if __name__ == "__main__":
    main()
