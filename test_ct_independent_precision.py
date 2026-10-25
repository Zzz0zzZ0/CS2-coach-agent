import numpy as np
import pytest
from scipy.stats import t

from scripts.plan_ct_independent_precision import precision_scenario


def test_precision_assurance_matches_normal_residual_variance_simulation():
    result = precision_scenario(12, 0.05)
    sampled_sd = 0.05 * np.sqrt(np.random.default_rng(20261025).chisquare(6, 100000) / 6)
    widths = t.ppf(0.975, 6) * sampled_sd / np.sqrt(12)
    assert (widths <= 0.05).mean() == pytest.approx(
        result['probability_width_within_target_under_normal_independent_homoscedastic_model'], abs=0.004)
    assert precision_scenario(24, 0.05)['half_width_if_residual_sd_equals_assumed_sigma'] < result['half_width_if_residual_sd_equals_assumed_sigma']
    assert precision_scenario(12, 0.05, variance_multiplier=2)['half_width_if_residual_sd_equals_assumed_sigma'] > result['half_width_if_residual_sd_equals_assumed_sigma']
    with pytest.raises(ValueError):
        precision_scenario(9, 0.05)
