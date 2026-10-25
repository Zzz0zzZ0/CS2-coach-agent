"""Synthetic source-only pattern checks; cluster labels have no tactical meaning."""

import numpy as np

from scripts.analyze_ct_deployment_patterns import bootstrap_stability, fit_patterns

CFG = {"k_candidates": [2, 3], "n_init": 3, "max_iter": 50, "seed": 20261025,
       "source_radius_quantile": .95, "minimum_cluster_support": 5, "series_bootstrap_replicates": 4}


def test_query_observations_cannot_change_source_selected_clusters():
    rng = np.random.default_rng(5)
    source = np.concatenate([rng.normal(-3, .1, (20, 3)), rng.normal(3, .1, (20, 3))])
    first = fit_patterns(source, source[:3], CFG)
    after = fit_patterns(source, np.full((3, 3), 100), CFG)
    assert first["status"] == "fitted" and first["k"] == 2
    assert after["k"] == first["k"]
    np.testing.assert_array_equal(first["centers"], after["centers"])
    assert not after["query_assigned"].any()
    bootstrap = bootstrap_stability(source, first["source_labels"], ["a", "b"] * 20, first["k"], CFG)
    assert len(bootstrap["ARI_values"]) + bootstrap["unsupported"] == 4
    assert bootstrap["mean_ARI"] > .9


def test_collapsed_embedding_and_insufficient_series_are_reported():
    result = fit_patterns(np.zeros((10, 3)), np.zeros((2, 3)), CFG)
    assert result["status"] == "unsupported"
    assert all(row["status"] == "unsupported" for row in result["candidates"])
    bootstrap = bootstrap_stability(np.zeros((10, 3)), np.zeros(10), ["same"] * 10, 2, CFG)
    assert bootstrap["mean_ARI"] is None and bootstrap["unsupported"] == 4
