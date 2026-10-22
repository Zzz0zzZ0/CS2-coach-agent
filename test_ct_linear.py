"""模拟示例: lightweight CT inference, causality, and export contracts."""

import copy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from app.services.ct_feature_service import feature_sequence
from app.services.ct_linear_service import CTLinearPredictor, linear_inputs

MODEL = Path(__file__).parent / "datasets/models/ct_linear_v1.json"


def snapshots():
    return [{"second": second, "players": [
        {"steamid": str(i), "position": [i * 100 + second, i * 40, 20],
         "health": 100 if i < 4 else 0, "equipment_value": 3000, "place": "BombsiteA" if i < 2 else "Middle"}
        for i in range(5)]} for second in (10, 12, 15, 18, 20)]


def test_linear_model_is_causal_and_permutation_translation_invariant():
    predictor = CTLinearPredictor(MODEL)
    rows = snapshots()
    forecast = predictor.predict(rows)
    predicted = np.array([r["prediction"] for r in forecast["forecasts"]])
    np.testing.assert_allclose(predicted[:, :6].sum(-1), 1)
    assert (predicted[:, 5] >= .2).all() and (predicted >= 0).all()
    assert (predicted[:, 6] <= predicted[:, 7]).all()
    moved = copy.deepcopy(rows)
    for row in moved:
        row["players"] = list(reversed(row["players"]))
        for player in row["players"]:
            player["position"] = [x + 1000 for x in player["position"]]
    transformed = [r["prediction"] for r in predictor.predict(moved)["forecasts"]]
    np.testing.assert_allclose(transformed, predicted, atol=1e-7, rtol=0)
    future = copy.deepcopy(rows)
    for player in future[-1]["players"]:
        player["position"] = [10000, 5000, 1000]
        player["place"] = "BombsiteB"
    assert predictor.predict(future)["forecasts"] == forecast["forecasts"]
    for player in future[-2]["players"]:
        player["place"] = "BombsiteB"
    assert predictor.predict(future)["forecasts"][:3] == forecast["forecasts"][:3]
    data = {k: value[None] for k, value in feature_sequence(rows).items()}
    original = linear_inputs(data)[0]
    data["targets"][:] = 999
    np.testing.assert_array_equal(linear_inputs(data)[0], original)


@pytest.mark.parametrize("problem", ["version", "shape", "scale", "nan"])
def test_invalid_model_rejected(tmp_path, problem):
    model = json.loads(MODEL.read_text())
    if problem == "version":
        model["feature_version"] = "unmatched-version"
    elif problem == "shape":
        model["coefficients"] = []
    elif problem == "scale":
        model["std"][0] = 0
    else:
        model["mean"][0] = float("nan")
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model))
    with pytest.raises(ValueError):
        CTLinearPredictor(path)


def test_offline_entrypoint_keeps_ct_scope_and_refuses_overwrite(tmp_path, monkeypatch):
    from scripts.predict_ct_opening import main
    source = tmp_path / "snapshots.json"
    output = tmp_path / "prediction.json"
    source.write_text(json.dumps({"map_name": "synthetic", "source_demo_sha256": "synthetic",
        "rounds": [{"round_number": 1, "side": "CT", "status": "ok", "snapshots": snapshots()},
                   {"round_number": 1, "side": "T", "status": "ok", "snapshots": snapshots()}]}))
    monkeypatch.setattr(sys, "argv", ["predict_ct_opening", "--snapshots", str(source), "--output", str(output)])
    main()
    content = output.read_bytes()
    result = json.loads(content)
    assert len(result["rounds"]) == 1 and result["rounds"][0]["side"] == "CT"
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and output.read_bytes() == content
