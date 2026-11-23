"""Coordination engine: must catch the real network and must NOT flag organic
accounts, generic commenters, or accounts that merely posted near the same time."""


def _flagged(pipeline):
    return {a for g in pipeline["groups"]
            if g["classification"] != "insufficient evidence"
            for a in g["account_ids"]}


def test_detects_the_coordinated_network(pipeline):
    flagged = _flagged(pipeline)
    truth = set(pipeline["truth"]["coordinated_accounts"])
    assert truth.issubset(flagged), f"missed coordinated accounts: {truth - flagged}"


def test_no_false_positives(pipeline):
    """No organic, debunk, generic, or noise account is flagged."""
    flagged = _flagged(pipeline)
    truth = set(pipeline["truth"]["coordinated_accounts"])
    assert flagged == truth, f"false positives: {flagged - truth}"


def test_generic_commenters_never_coordinated(pipeline):
    """The near-simultaneous generic GTA commenters must not form a group —
    this is the exact failure mode the rebuild fixes."""
    flagged = _flagged(pipeline)
    gamers = {a for a in pipeline["accounts"] if a.startswith("yt:gamer")}
    assert not (flagged & gamers), "generic commenters wrongly flagged"


def test_group_is_strong_with_evidence(pipeline):
    """The network group is classified strong, with a media/caption signal and a
    full evidence trail."""
    groups = [g for g in pipeline["groups"]
              if g["classification"] != "insufficient evidence"]
    assert groups, "no coordinated group found"
    g = groups[0]
    assert g["classification"] == "strong coordination indicators"
    assert "shared_media" in g["detectors"]
    assert g["evidence"] and g["_detail_lines"]
    assert g["confidence"] in ("High", "Medium", "Low")


def test_temporal_proximity_alone_insufficient(pipeline):
    """Explicit guard: accounts linked ONLY by account_similarity / timing never
    survive into a group (every retained edge needs a content signal)."""
    for g in pipeline["groups"]:
        if g["classification"] == "insufficient evidence":
            continue
        content = set(g["content_detectors"])
        assert content, f"group {g['group_id']} has no content signal"
