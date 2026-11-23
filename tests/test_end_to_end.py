"""End-to-end: the full CLI pipeline runs, writes every required artifact, and
the evaluation metrics clear sensible bars on the synthetic ground truth."""

import os
import json
import tempfile

from casmd.config import Config
from casmd.run import run, DEMO_INCIDENT
from casmd import evaluate as ev


def test_full_run_writes_all_exports(tmp_path):
    cfg = Config(incident=DEMO_INCIDENT)
    cfg.db_path = str(tmp_path / "casmd.sqlite")
    cfg.out_dir = str(tmp_path / "out")
    run(cfg, reseed=True)
    for name in ("report.json", "posts.json", "posts.csv",
                 "coordinated_groups.csv", "media_clusters.json",
                 "narratives.json", "propagation_graph.json", "timeline.json",
                 "dashboard.html"):
        path = os.path.join(cfg.out_dir, name)
        assert os.path.exists(path), f"missing export: {name}"
        assert os.path.getsize(path) > 0


def test_propagation_timeline_reconstructed(pipeline):
    tl = pipeline["prop"]["timeline"]
    assert tl, "empty timeline"
    # earliest observed event is a coordinated wave-1 upload
    assert tl[0]["post_id"].startswith("yt:net")
    # the note makes the observed-vs-origin distinction explicit
    assert "not necessarily the original" in pipeline["prop"]["note"].lower()


def test_cross_platform_propagation_present(pipeline):
    edges = pipeline["prop"]["edges"]
    types = {e["edge_type"] for e in edges}
    assert "cross_platform_media" in types or "telegram_forward" in types


def test_evaluation_metrics_clear_bars():
    res = ev.evaluate(verbose=False)
    assert res["relevance"]["f1"] >= 0.9
    assert res["coordination"]["precision"] >= 0.9
    assert res["coordination"]["recall"] >= 0.9
    assert res["media"]["recall"] >= 0.9
