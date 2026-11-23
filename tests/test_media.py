"""Media correlation: reuploaded / re-encoded / cropped copies of the ship video
must land in one high-confidence cluster that spans both platforms."""


def test_reuploads_clustered_together(pipeline):
    truth_copies = set(pipeline["truth"]["media_cluster_posts"])
    best = max((set(c.post_ids) & truth_copies for c in pipeline["media_clusters"]),
              key=len, default=set())
    recall = len(best) / len(truth_copies)
    assert recall >= 0.9, f"media cluster recall too low: {recall}"


def test_video_cluster_is_cross_platform_high_confidence(pipeline):
    vids = [c for c in pipeline["media_clusters"]
            if "exact_file" in c.match_types or "keyframes" in c.match_types]
    assert vids, "no high-confidence video cluster"
    c = vids[0]
    assert c.confidence == "high"
    assert set(c.platforms) == {"youtube", "telegram"}


def test_thumbnail_only_cluster_is_not_high(pipeline):
    """Thumbnail-only matches must not be reported as 'identical video'."""
    for c in pipeline["media_clusters"]:
        if c.match_types == ["thumbnail_similar"]:
            assert c.confidence != "high"
            assert "NOT proof" in c.evidence
