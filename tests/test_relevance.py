"""Relevance engine: the incident dataset must admit real incident posts and
keep unrelated / generic content out."""


def _by_scenario(pipeline, s):
    return [pid for pid, sc in pipeline["truth"]["scenario"].items() if sc == s]


def test_incident_posts_admitted(pipeline):
    """Scenario 1/2/4 incident posts are admitted as relevant."""
    by_id = pipeline["by_id"]
    truth_rel = set(pipeline["truth"]["relevant_posts"])
    admitted = {p.post_id for p in pipeline["posts"]
                if p.relevance_decision == "relevant"}
    recall = len(admitted & truth_rel) / len(truth_rel)
    assert recall >= 0.9, f"relevance recall too low: {recall}"


def test_unrelated_gaming_excluded(pipeline):
    """Scenario 3 (GTA / gaming / generic comments / noise) must be excluded."""
    by_id = pipeline["by_id"]
    for pid in _by_scenario(pipeline, 3):
        p = by_id[pid]
        assert p.relevance_decision != "relevant", \
            f"unrelated post wrongly admitted: {p.text!r}"


def test_generic_comments_flagged_and_excluded(pipeline):
    """Generic comments ('First', 'Nice video', 'GTA 6 is amazing') are flagged
    generic and never admitted as relevant incident content."""
    by_id = pipeline["by_id"]
    generic_texts = {"first", "first comment", "nice video", "amazing",
                     "gta 6 is amazing", "best youtubers ever"}
    hits = [p for p in pipeline["posts"]
            if (p.text or "").strip().lower() in generic_texts]
    assert hits, "expected some generic comments in the dataset"
    for p in hits:
        assert p.is_generic, f"not flagged generic: {p.text!r}"
        assert p.relevance_decision != "relevant", \
            f"generic comment admitted: {p.text!r}"


def test_comment_parent_gating(pipeline):
    """A comment under an irrelevant (gaming) video is excluded even if its own
    text somehow scored — parent gating is enforced."""
    by_id = pipeline["by_id"]
    gta_comments = [p for p in pipeline["posts"]
                    if p.kind == "comment" and p.parent_id == "yt:gta6"]
    assert gta_comments, "expected comments under the gaming video"
    assert all(p.relevance_decision != "relevant" for p in gta_comments)


def test_three_category_decisions(pipeline):
    """Every post carries one of the three relevance decisions + a reason."""
    for p in pipeline["posts"]:
        assert p.relevance_decision in ("relevant", "review", "irrelevant")
        assert p.relevance_reason
        assert 0.0 <= p.relevance_score <= 1.0
