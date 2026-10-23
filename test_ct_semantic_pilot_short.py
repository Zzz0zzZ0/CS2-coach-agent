"""Synthetic process-pilot checks; these are not human ratings."""

import copy

import pytest

from scripts.shorten_ct_semantic_pilot import payload_hash, shorten


def fixture():
    payload = {"version": "full", "queries": [{"id": "Q01", "query": {"map": "x"},
               "candidates": [{"id": c, "record": {"map": c}} for c in ("a", "b", "c")]}]}
    payload["payload_sha256"] = payload_hash(payload)
    key = {"payload_sha256": payload["payload_sha256"], "queries": {"Q01": {
        "candidates": {c: {"id": c} for c in ("a", "b", "c")},
        "method_rankings": {"common_state_5snap": ["a", "c"], "deterministic_random": ["a", "b", "c"]}}}}
    return payload, key


def test_overlap_is_skipped_and_reblinding_preserves_private_mapping_without_mutation():
    payload, key = fixture()
    before = copy.deepcopy((payload, key))
    result, private = shorten(payload, key)
    assert (payload, key) == before
    assert (result, private) == shorten(payload, key)
    assert result["payload_sha256"] != payload["payload_sha256"]
    assert private["payload_sha256"] == payload_hash(result)
    assert {c["id"] for c in result["queries"][0]["candidates"]} == {"C01", "C02"}
    details = private["queries"]["Q01"]
    assert {c["id"] for c in details["candidates"].values()} == {"a", "b"}
    for candidate in result["queries"][0]["candidates"]:
        assert candidate["record"]["map"] == details["candidates"][candidate["id"]]["id"]


@pytest.mark.parametrize("fault", ["hash", "key", "overlap", "missing"])
def test_invalid_inputs_are_rejected(fault):
    payload, key = fixture()
    if fault == "hash":
        payload["version"] = "changed"
    elif fault == "key":
        key["payload_sha256"] = "wrong"
    elif fault == "overlap":
        key["queries"]["Q01"]["method_rankings"]["deterministic_random"] = ["a"]
    else:
        del key["queries"]["Q01"]["candidates"]["b"]
    with pytest.raises(ValueError):
        shorten(payload, key)
