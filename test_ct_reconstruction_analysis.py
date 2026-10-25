"""Synthetic observation-distance and series-weighting checks, not tactical gold."""

import numpy as np

from app.services.ct_deployment_service import deployment_sequence
from scripts.evaluate_ct_reconstruction import equal_series, observation_distances, statistics_sequence
from test_ct_linear import snapshots


def test_direct_matching_respects_one_player_correspondence_for_the_window():
    result = deployment_sequence(snapshots(), [])
    data = {key: np.repeat(result[key][None], 3, axis=0)
            for key in ("nodes", "edges", "node_mask", "node_feature_mask", "pair_mask")}
    permutation = [1, 0, 2, 3, 4]
    for key in data:
        changed = data[key][0][:, permutation]
        if key in ("edges", "pair_mask"):
            changed = changed[:, :, permutation]
        data[key][1] = changed
        data[key][2, -1] = changed[-1]
    distance = observation_distances(data)
    np.testing.assert_allclose(distance, distance.T, atol=1e-12)
    np.testing.assert_allclose(distance.diagonal(), 0, atol=1e-12)
    assert distance[0, 1] < 1e-12
    assert distance[0, 2] > 1e-8
    statistics = statistics_sequence(data)
    assert statistics.shape == (3, 120)
    np.testing.assert_allclose(statistics, np.repeat(statistics[:1], 3, axis=0), atol=1e-6)


def test_valid_zero_and_unknown_motion_have_distinct_observation_vectors():
    result = deployment_sequence(snapshots(), [])
    data = {key: np.repeat(result[key][None], 2, axis=0)
            for key in ("nodes", "edges", "node_mask", "node_feature_mask", "pair_mask")}
    data["nodes"][..., 13:] = 0
    data["node_feature_mask"][1, ..., 13:] = False
    assert observation_distances(data)[0, 1] > 0
    assert not np.array_equal(statistics_sequence(data)[0], statistics_sequence(data)[1])


def test_series_weighting_does_not_count_more_rounds_as_more_independent_series():
    from scripts.evaluate_ct_reconstruction import paired_summary
    values = np.asarray([.1] * 10 + [.9])
    series = ["a"] * 10 + ["b"]
    assert abs(equal_series(values, series) - .5) < 1e-12
    result = paired_summary(values, values * 2, series)
    assert result["series_count"] == 2
    assert abs(result["equal_series_reduction_pct"] - 50) < 1e-10
    np.testing.assert_allclose(result["descriptive_95pct_interval"], [50, 50])
