"""模拟示例: deterministic neighbors and geometry-only proxy boundaries."""

import numpy as np
import pytest

from app.services.ct_retrieval_service import nearest_candidates, nearest_common_candidates, geometry_signature, geometry_diagnostic


def test_rankings_are_stable_and_geometry_proxy_is_not_a_tactical_score():
    ranking, distance = nearest_candidates([[1, 0]], [[0, 0], [2, 0], [4, 0]], 2)
    assert ranking.tolist() == [[0, 1]]
    result = geometry_diagnostic(ranking, distance, ranking)
    assert result["top5_geometry_neighbor_overlap"] == 1
    assert "not tactical" in result["claim"]
    with pytest.raises(ValueError):
        nearest_candidates([[float("nan")]], [[0]])


def test_geometry_excludes_dead_pairs_and_ignores_player_order():
    rng = np.random.default_rng(7)
    points = rng.normal(size=(2, 5, 5, 3))
    edges = np.linalg.norm(points[..., :, None, :] - points[..., None, :, :], axis=-1)
    alive = np.ones((2, 5, 5), dtype=bool); alive[1, 4, 0] = False
    mask, original = geometry_signature({"edges": edges, "alive": alive})
    assert mask.tolist() == [True, False] and original.shape == (1, 50)
    permutation = [3, 2, 4, 1, 0]
    _, permuted = geometry_signature({"edges": edges[:, :, permutation][:, :, :, permutation], "alive": alive[:, :, permutation]})
    np.testing.assert_array_equal(original, permuted)


def test_common_retrieval_masks_undefined_distances():
    query = np.zeros((1, 40)); library = np.zeros((2, 40))
    library[0, 6:8] = 999
    library[1, 0] = 1
    mask = np.ones((1, 40)); mask[0, 6:8] = 0
    ranking, _ = nearest_common_candidates(query, library, mask, np.ones_like(library), 1)
    assert ranking.tolist() == [[0]]
    full, d1 = nearest_common_candidates(query, library, np.ones_like(query), np.ones_like(library))
    standard, d2 = nearest_candidates(query, library)
    np.testing.assert_array_equal(full, standard)
    np.testing.assert_allclose(d1, d2)


def test_offline_retrieval_excludes_same_pair_and_T_queries():
    from scripts.retrieve_ct_opening import retrieve
    features = {"nodes": np.zeros((5, 5, 8), dtype=np.float32), "edges": np.zeros((5, 5, 5), dtype=np.float32),
                "alive": np.ones((5, 5), dtype=bool), "target_mask": np.ones((5, 8))}
    features["nodes"][..., 4] = 1
    library = [{"id": "excluded", "series": "g2-vs-navi_dust2", "features": features},
               {"id": "kept", "series": "mouz-vs-vitality_dust2", "features": features}]
    snapshots = [{"second": sec, "players": [{"steamid": str(i), "position": [i, 0, 0], "health": 100,
                  "equipment_value": 1000, "place": "Middle"} for i in range(5)]} for sec in (10, 12, 15, 18, 20)]
    document = {"map_name": "synthetic", "source_demo_sha256": "synthetic", "rounds": [
        {"round_number": 1, "side": "CT", "team": "G2", "status": "ok", "snapshots": snapshots},
        {"round_number": 1, "side": "T", "team": "NAVI", "status": "ok", "snapshots": snapshots}]}
    result = retrieve(document, library)
    assert result["excluded_same_team_pair"] == 1 and len(result["rounds"]) == 1
    assert result["rounds"][0]["candidates"][0]["id"] == "kept"
    assert result["rounds"][0]["candidates"][0]["relevance_status"] == "unreviewed"
