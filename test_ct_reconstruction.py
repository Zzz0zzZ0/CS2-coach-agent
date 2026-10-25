"""模拟示例: reconstruction contracts, not tactical labels or human acceptance."""

import copy
import unittest

import numpy as np

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Optional research GPU environment supplies PyTorch")
class ReconstructionContracts(unittest.TestCase):
    def setUp(self):
        from app.services.ct_deployment_service import deployment_sequence
        from scripts.run_ct_reconstruction import ReconstructionModel, reconstruction_loss
        self.model_class, self.loss = ReconstructionModel, reconstruction_loss
        torch.set_num_threads(1)
        torch.manual_seed(0)
        rows = [{"second": t, "players": [{
            "steamid": str(i), "position": [i * 110 + t * 10 * (i + 1), i * 40 + t * i, i * 20],
            "health": 100 - i * 10 if i < 4 else 0, "equipment_value": 1000 + 500 * i,
            "place": "BombsiteA" if i == 0 else "BombsiteB" if i == 1 else "Middle",
        } for i in range(5)]} for t in (10, 12, 15, 18, 20)]
        result = deployment_sequence(rows, [])
        self.arrays = {key: result[key][None] for key in ("nodes", "edges", "node_mask", "node_feature_mask", "pair_mask")}
        self.batch = {key: torch.from_numpy(value) for key, value in self.arrays.items()}

    def reordered(self, permutation):
        b = self.batch
        return {key: value[:, :, permutation][:, :, :, permutation] if key in ("edges", "pair_mask")
                else value[:, :, permutation] for key, value in b.items()}

    def perfect_prediction(self):
        result = {key: self.batch[key].clone() for key in ("nodes", "edges")}
        result["nodes"][..., :5] *= 40
        result["nodes"][..., 7] = (self.batch["node_mask"].float() * 2 - 1) * 40
        result["nodes"][..., 10:13] *= 40
        return result

    def test_one_joint_matching_preserves_trajectories_and_pair_endpoints(self):
        p = self.model_class("graph_static").permutations
        prediction = self.perfect_prediction()
        original = self.loss(prediction, self.batch, p)[0]
        self.assertLess(original.item(), 1e-7)
        reordered = self.reordered([3, 0, 4, 1, 2])
        torch.testing.assert_close(self.loss(prediction, reordered, p)[0], original)
        broken = {key: value.clone() for key, value in self.batch.items()}
        swapped = self.reordered([1, 0, 2, 3, 4])
        for key in broken:
            broken[key][:, -1] = swapped[key][:, -1]
        self.assertGreater(self.loss(prediction, broken, p)[0].item(), 1e-4)
        wrong_edges = copy.deepcopy(prediction)
        wrong_edges["edges"][:, :, 0, 1] += 2
        wrong_edges["edges"][:, :, 1, 0] += 2
        self.assertGreater(self.loss(wrong_edges, self.batch, p)[1][0, -1].item(), .01)

    def test_unknown_motion_and_dead_fields_do_not_become_zero_targets(self):
        p = self.model_class("graph_static").permutations
        prediction = self.perfect_prediction()
        before = self.loss(prediction, self.batch, p)[0]
        prediction["nodes"][:, 0, :, 13:] = 999
        prediction["nodes"][:, :, 4, :7] = 999
        prediction["nodes"][:, :, 4, 8:] = 999
        prediction["edges"][:, :, 4] = 999
        prediction["edges"][:, :, :, 4] = 999
        torch.testing.assert_close(self.loss(prediction, self.batch, p)[0], before)
        prediction["nodes"][:, 1:, :4, 13] += 1
        self.assertGreater(self.loss(prediction, self.batch, p)[1][0, 5].item(), .1)

    def test_all_conditions_are_permutation_invariant_and_receive_gradients(self):
        from scripts.run_ct_reconstruction import CONDITIONS
        for condition in CONDITIONS:
            with self.subTest(condition=condition):
                model = self.model_class(condition)
                prediction, z = model(self.batch)
                after, reordered_z = model(self.reordered([4, 1, 3, 0, 2]))
                torch.testing.assert_close(z, reordered_z, atol=1e-5, rtol=0)
                for key in prediction:
                    torch.testing.assert_close(prediction[key], after[key], atol=1e-5, rtol=0)
                loss = self.loss(prediction, self.batch, model.permutations)[0].mean()
                loss.backward()
                for module in (model.encoder, model.decoder, model.gru):
                    if module is not None:
                        grads = [parameter.grad for parameter in module.parameters()]
                        self.assertTrue(all(g is not None and torch.isfinite(g).all() for g in grads))
                        self.assertGreater(sum(g.abs().sum().item() for g in grads), 0)
                if model.family == "graph":
                    self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.layers.parameters()))

    def test_prefix_causality_and_input_ablations(self):
        for condition, node_start, edge_start in (("graph_gru_no_motion", 13, 3), ("graph_gru_common", 8, 1)):
            model = self.model_class(condition).eval()
            altered = {key: value.clone() for key, value in self.batch.items()}
            altered["nodes"][..., node_start:] += 10
            altered["edges"][..., edge_start:] += 10
            torch.testing.assert_close(model(altered)[1], model(self.batch)[1])
        model = self.model_class("graph_gru").eval()
        before = model.encode(self.batch)[1]
        altered = {key: value.clone() for key, value in self.batch.items()}
        altered["nodes"][:, -1, :4, 5] /= 2
        altered["nodes"][:, -1, :4, 13] += 2
        after = model.encode(altered)[1]
        torch.testing.assert_close(before[:, :4], after[:, :4], atol=1e-7, rtol=0)
        self.assertFalse(torch.allclose(before[:, -1], after[:, -1]))

    def test_input_and_split_boundaries_reject_invalid_data(self):
        from scripts.run_ct_reconstruction import validate_fold, validate_inputs
        validate_inputs(self.arrays)
        for key, replacement in (("nodes", np.zeros((1, 4, 5, 15))), ("node_mask", self.arrays["node_mask"].astype(float))):
            altered = dict(self.arrays)
            altered[key] = replacement
            with self.assertRaises(ValueError):
                validate_inputs(altered)
        altered = {key: value.copy() for key, value in self.arrays.items()}
        altered["node_feature_mask"][:, 0, 0, 13] = True
        with self.assertRaises(ValueError):
            validate_inputs(altered)
        index = [{"series": str(i), "map": "a"} for i in range(3)]
        fold = {"task": "G3", "train": [0], "validation": [1], "test": [2]}
        validate_fold(fold, index)
        with self.assertRaises(ValueError):
            validate_fold({**fold, "test": [1]}, index)
        with self.assertRaises(ValueError):
            validate_fold({**fold, "task": "G4"}, index)


if __name__ == "__main__":
    unittest.main()
