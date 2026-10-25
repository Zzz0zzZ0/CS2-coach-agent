import numpy as np
import pytest

from app.services.ct_context_retrieval_service import (
    context_embedding, context_groups, fused_embedding, normalize_source, squared_distance,
)


def observation():
    return {"id": "one", "freeze_end_tick": 100, "score_before": {"CT": 1, "T": 2},
            "snapshots": [{"second": second, "tick": 100 + second * 64,
                           "equipment_total": {"CT": 0, "T": 12345},
                           "CT_pitch_yaw_in_frozen_player_order": [[45, 90]] * 5,
                           "utility": {"recorded_ct_throws": {}, "unattributed_recorded_throws": 0}}
                          for second in (10, 12, 15, 18, 20)]}


def test_context_keeps_known_zero_unknown_and_observer_information_separate():
    row = observation()
    expected = context_groups([row])
    row["snapshots"][0]["equipment_total"]["T"] = 999999
    row["snapshots"][0]["CT_pitch_yaw_in_frozen_player_order"] = None
    for key, values in expected.items():
        np.testing.assert_equal(context_groups([row])[key], values)
    assert expected["utility"].shape == (1, 30) and not expected["utility"].any()
    row["snapshots"][0]["utility"]["unattributed_recorded_throws"] = 1
    row["snapshots"][0]["equipment_total"]["CT"] = None
    row["score_before"] = None
    groups = context_groups([row])
    assert np.isnan(groups["utility"][0, :6]).all() and np.isnan(groups["equipment"][0, 0])
    assert np.isnan(groups["score"]).all()
    with pytest.raises(ValueError, match="token"):
        row["snapshots"][0]["utility"]["recorded_ct_throws"]["new_weapon"] = 1
        context_groups([row])


def test_source_only_scaling_matches_pair_distance_and_does_not_fit_queries():
    source = np.array([[0, 1], [2, 2], [4, 0.]])
    query = np.array([[1, 7.]])
    s, q, metadata = normalize_source(source, query)
    distance = squared_distance(s, s)
    assert distance[~np.eye(3, dtype=bool)].mean() == pytest.approx(1)
    other_s, _, other_metadata = normalize_source(source, query * 1000)
    np.testing.assert_array_equal(s, other_s)
    assert metadata == other_metadata
    assert np.isfinite(normalize_source(np.zeros((3, 2)), query)[1]).all()


def test_joint_vectors_equal_weighted_distances_and_missing_queries_are_explicit():
    rng = np.random.default_rng(8)
    source, query = rng.normal(size=(7, 4)), rng.normal(size=(3, 4))
    src = {"equipment": rng.normal(size=(7, 5)), "score": rng.normal(size=(7, 2))}
    qry = {"equipment": rng.normal(size=(3, 5)), "score": rng.normal(size=(3, 2))}
    context = context_embedding(src, qry, ("equipment", "score"))
    s, q, _ = fused_embedding(source, query, context, 0.5)
    bs, bq, _ = normalize_source(source, query)
    np.testing.assert_allclose(squared_distance(q, s),
        0.5 * squared_distance(bq, bs) + 0.5 * squared_distance(context["queries"], context["source"]), atol=1e-12)
    qry["equipment"][0, 0] = np.nan
    assert context_embedding(src, qry, ("equipment", "score"))["query_supported"].tolist() == [False, True, True]
    src["equipment"][0, 0] = np.nan
    assert not context_embedding(src, qry, ("equipment", "score"))["source_supported"]


def test_ranking_keeps_stable_ties_and_marks_empty_or_unknown_conditions():
    from scripts.evaluate_ct_context_retrieval import rank_arrays
    index = [{"map": "a"}, {"map": "b"}, {"map": "b"}]
    rank, distance = rank_arrays(np.array([[1., 1.]]), np.array([0]), np.array([1, 2]), index, 3)
    assert rank[0, 0].tolist() == [1, 2, -1]
    assert rank[0, 1].tolist() == [-1, -1, -1]
    rank, _ = rank_arrays(np.array([[np.inf, np.inf]]), np.array([0]), np.array([1, 2]), index, 3)
    assert (rank == -1).all()
