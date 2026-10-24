"""Synthetic invariance and temporal-isolation checks of the new non-graph control."""
import copy

import pytest

torch = pytest.importorskip("torch", reason="Research GPU environment supplies optional PyTorch")

from app.services.ct_feature_service import feature_sequence
from scripts.run_ct_information_control import PermutationMLP
from test_ct_linear import snapshots


def test_complete_node_edge_permutations_and_future_isolation():
    torch.set_num_threads(1)
    torch.manual_seed(0)
    data = {k: torch.from_numpy(v[None]) for k, v in feature_sequence(snapshots()).items() if k in ("nodes", "edges", "alive")}
    model = PermutationMLP().eval()
    with torch.no_grad():
        model.predict.weight.normal_(0, .1)
        for temporal in (False, True):
            rec, pred, representation = model(data, temporal)
            changed = copy.deepcopy(data)
            perm = [4, 1, 3, 0, 2]
            changed["nodes"] = changed["nodes"][:, :, perm]
            changed["alive"] = changed["alive"][:, :, perm]
            changed["edges"] = changed["edges"][:, :, perm][:, :, :, perm]
            after = model(changed, temporal)
            for a, b in zip((rec, pred, representation), after):
                torch.testing.assert_close(a, b, atol=1e-5, rtol=0)
            changed = copy.deepcopy(data)
            changed["nodes"][:, 4] = 999
            changed["edges"][:, 4] = 999
            torch.testing.assert_close(model(changed, temporal)[1], pred, atol=1e-7, rtol=0)
            changed["nodes"][:, 3] = 500
            torch.testing.assert_close(model(changed, temporal)[1][:, :3], pred[:, :3], atol=1e-7, rtol=0)
        # Dead-player stale state and edges must not become an extra information source.
        changed = copy.deepcopy(data)
        changed["nodes"][:, :, 4] = 999
        changed["edges"][:, :, 4] = 999
        changed["edges"][:, :, :, 4] = 999
        torch.testing.assert_close(model(changed, False)[0], model(data, False)[0], atol=1e-6, rtol=0)


def test_invalid_shape_is_rejected():
    with pytest.raises(ValueError):
        PermutationMLP()({"nodes": torch.zeros(1, 4, 5, 8), "edges": torch.zeros(1, 4, 5, 5),
                          "alive": torch.ones(1, 4, 5, dtype=torch.bool)}, False)
