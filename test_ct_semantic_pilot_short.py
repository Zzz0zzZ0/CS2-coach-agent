"""Synthetic process-pilot checks; these are not human ratings."""

import copy
import json
import re
import zipfile

import pytest

from scripts.shorten_ct_semantic_pilot import ROOT, distribute, payload_hash, shorten


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


def test_distribution_keeps_every_pair_once_and_private_keys_out_of_packets(tmp_path):
    payload, key = fixture()
    second = copy.deepcopy(payload["queries"][0])
    second["id"] = "Q02"
    payload["queries"].append(second)
    key["queries"]["Q02"] = copy.deepcopy(key["queries"]["Q01"])
    payload["payload_sha256"] = key["payload_sha256"] = payload_hash(payload)
    before = copy.deepcopy(payload)
    output = tmp_path / "packets"
    distribute(payload, key, (ROOT / "scripts/templates/ct_pilot_review.html").read_text(encoding="utf-8"), output)
    seen = []
    for archive in output.glob("CT-Q*.zip"):
        with zipfile.ZipFile(archive) as bundle:
            assert set(bundle.namelist()) == {"review.html", "说明.txt"}
            html = bundle.read("review.html").decode()
            data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)[1])
            assert payload_hash(data) == data["payload_sha256"]
            seen.extend((q["id"], c["id"]) for q in data["queries"] for c in q["candidates"])
    assert len(seen) == len(set(seen)) == 6
    assert payload == before
