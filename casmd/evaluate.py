"""
Evaluation harness — measures the detector against the synthetic ground truth.

Runs the full pipeline on the synthetic ship-bombing incident, then compares the
system's output to the ground-truth labels baked into the synthetic generator,
and reports precision / recall with explicit false positives and false negatives
for:

  * incident relevance   (which posts were admitted)
  * coordination         (which accounts were flagged as coordinated)
  * media correlation    (were the reuploaded video copies clustered together)
  * origin/timeline      (earliest observed upload)

This measures the system honestly; it does not tune thresholds to make the
numbers look good, and it keeps realistic edge cases (generic comments posted
near-simultaneously, debunkers, organic chatter).

    python -m casmd.evaluate
"""

from __future__ import annotations

import os
import json
import tempfile

from .config import Config
from .store import Store
from .run import run, DEMO_INCIDENT


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def evaluate(verbose=True):
    tmp = tempfile.mkdtemp(prefix="casmd_eval_")
    cfg = Config(incident=DEMO_INCIDENT)
    cfg.db_path = os.path.join(tmp, "casmd.sqlite")
    cfg.out_dir = os.path.join(tmp, "out")
    run(cfg, reseed=True)

    def _load(path):
        with open(path, encoding="utf-8") as f:   # explicit UTF-8 (Windows-safe)
            return json.load(f)

    truth = _load("data/synthetic_ground_truth.json")
    posts = _load(os.path.join(cfg.out_dir, "posts.json"))
    report = _load(os.path.join(cfg.out_dir, "report.json"))
    groups = report["coordinated_groups"]
    media = _load(os.path.join(cfg.out_dir, "media_clusters.json"))
    timeline = _load(os.path.join(cfg.out_dir, "timeline.json"))

    results = {}

    # ---- relevance -------------------------------------------------------- #
    truth_rel = set(truth["relevant_posts"])
    truth_irr = set(truth["irrelevant_posts"])
    pred_rel = {p["post_id"] for p in posts if p["relevance"]["decision"] == "relevant"}
    tp = len(pred_rel & truth_rel)
    fp = len(pred_rel - truth_rel)
    fn = len(truth_rel - pred_rel)
    p, r, f = _prf(tp, fp, fn)
    results["relevance"] = {"precision": p, "recall": r, "f1": f,
                            "tp": tp, "fp": fp, "fn": fn,
                            "false_positives": sorted(pred_rel - truth_rel),
                            "false_negatives": sorted(truth_rel - pred_rel)}

    # ---- coordination ----------------------------------------------------- #
    truth_coord = set(truth["coordinated_accounts"])
    pred_coord = {a for g in groups
                  if g["classification"] != "insufficient evidence"
                  for a in g["account_ids"]}
    tp = len(pred_coord & truth_coord)
    fp = len(pred_coord - truth_coord)
    fn = len(truth_coord - pred_coord)
    p, r, f = _prf(tp, fp, fn)
    results["coordination"] = {"precision": p, "recall": r, "f1": f,
                               "tp": tp, "fp": fp, "fn": fn,
                               "false_positives": sorted(pred_coord - truth_coord),
                               "false_negatives": sorted(truth_coord - pred_coord),
                               "num_groups": len(groups)}

    # ---- media clustering ------------------------------------------------- #
    truth_media = set(truth["media_cluster_posts"])
    best = 0
    best_cluster = None
    for c in media:
        overlap = len(set(c["post_ids"]) & truth_media)
        if overlap > best:
            best, best_cluster = overlap, c["cluster_id"]
    purity = (best / len(set(media[best_cluster]["post_ids"]))
              if best_cluster is not None else 0.0)
    results["media"] = {
        "truth_copies": len(truth_media),
        "largest_cluster_contains": best,
        "recall": best / len(truth_media) if truth_media else 0.0,
        "cluster_purity": round(purity, 2),
        "num_clusters": len(media)}

    # ---- origin / timeline ------------------------------------------------ #
    earliest = timeline[0] if timeline else None
    results["origin"] = {
        "earliest_post": earliest["post_id"] if earliest else None,
        "earliest_is_coordinated": bool(earliest and earliest.get("coordinated")),
        "timeline_events": len(timeline)}

    if verbose:
        _print(results)
    return results


def _print(res):
    print("\n" + "=" * 68)
    print("  CASMD EVALUATION — synthetic ship-bombing incident")
    print("=" * 68)
    for key in ("relevance", "coordination"):
        m = res[key]
        print(f"\n[{key.upper()}]  precision={m['precision']:.2f}  "
              f"recall={m['recall']:.2f}  f1={m['f1']:.2f}  "
              f"(TP={m['tp']} FP={m['fp']} FN={m['fn']})")
        if m["false_positives"]:
            print(f"   false positives: {m['false_positives']}")
        if m["false_negatives"]:
            print(f"   false negatives: {m['false_negatives']}")
    m = res["media"]
    print(f"\n[MEDIA]  {m['largest_cluster_contains']}/{m['truth_copies']} "
          f"reuploaded copies grouped in one cluster "
          f"(recall={m['recall']:.2f}, purity={m['cluster_purity']}, "
          f"{m['num_clusters']} clusters total)")
    m = res["origin"]
    print(f"\n[ORIGIN] earliest observed = {m['earliest_post']} "
          f"(coordinated={m['earliest_is_coordinated']}, "
          f"{m['timeline_events']} timeline events)")
    print("\n" + "=" * 68 + "\n")


if __name__ == "__main__":
    evaluate()
