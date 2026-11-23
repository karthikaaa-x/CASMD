"""Shared fixtures: run the full pipeline once on the synthetic incident and
expose the in-memory results + ground truth to every test."""

import os
import tempfile
import pytest

from casmd.config import Config
from casmd.run import DEMO_INCIDENT
from casmd.store import Store
from casmd.collectors import synthetic
from casmd.analysis import (relevance, media as media_mod, narratives as narr,
                            coordination as coord, origin as origin_mod)


@pytest.fixture(scope="session")
def pipeline():
    """Run the analysis pipeline on the synthetic incident in memory."""
    inc = DEMO_INCIDENT
    cfg = Config(incident=inc)
    accounts_l, posts, truth = synthetic.generate(inc)
    accounts = {a.account_id: a for a in accounts_l}

    relevance.score_posts(inc, cfg, posts)
    assets = media_mod.build_assets(posts)
    media_clusters, post_to_cluster = media_mod.cluster(assets, cfg)
    relevance.apply_media_boost(cfg, posts, media_clusters)
    relevance.gate_comments(cfg, posts)

    rel_posts = [p for p in posts if p.relevance_decision == "relevant"]
    narr_posts = [p for p in rel_posts if not p.is_generic]
    narratives, assignments, per_post = narr.detect(narr_posts, cfg, post_to_cluster)
    groups, G, directed = coord.detect(rel_posts, accounts, cfg,
                                       media_clusters=media_clusters,
                                       post_to_cluster=post_to_cluster,
                                       per_post_narr=per_post)
    prop = origin_mod.analyze(rel_posts, per_post, media_clusters, post_to_cluster,
                              groups, narratives)
    return {
        "cfg": cfg, "posts": posts, "accounts": accounts, "truth": truth,
        "media_clusters": media_clusters, "post_to_cluster": post_to_cluster,
        "narratives": narratives, "per_post": per_post,
        "groups": groups, "prop": prop,
        "by_id": {p.post_id: p for p in posts},
    }
