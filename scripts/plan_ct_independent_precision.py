"""Conditional precision scenarios for a balanced six-map technical confirmation."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import scipy
from scipy.stats import chi2, t

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write


def precision_scenario(n, sigma, half_width=0.05, variance_multiplier=1.0):
    if n < 12 or n % 6 or sigma <= 0 or half_width <= 0 or variance_multiplier < 1:
        raise ValueError("At least two series per each of six maps and positive planning inputs required")
    df = n - 6
    critical = float(t.ppf(0.975, df))
    effective_sigma = sigma * np.sqrt(variance_multiplier)
    threshold = df * n * (half_width / (critical * effective_sigma)) ** 2
    return {"series": n, "maps": 6, "series_per_map": n // 6, "residual_df": df,
            "assumed_within_map_log_ratio_sigma": sigma, "variance_multiplier_sensitivity": variance_multiplier,
            "half_width_if_residual_sd_equals_assumed_sigma": critical * effective_sigma / np.sqrt(n),
            "probability_width_within_target_under_normal_independent_homoscedastic_model": float(chi2.cdf(threshold, df))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    source_path = ROOT / "datasets/evaluation/ct_reconstruction_development_report.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    g = source["tasks"]["G4"]["methods"]["graph_gru"]["by_series"]
    m = source["tasks"]["G4"]["methods"]["mlp_gru"]["by_series"]
    old = np.asarray([np.log(g[s]["loss"] / m[s]["loss"]) for s in sorted(g)])
    rows = [precision_scenario(n, sigma, variance_multiplier=inflation)
            for sigma in (0.02, 0.05, 0.10, 0.15) for inflation in (1.0, 1.5, 2.0) for n in (12, 18, 24, 36, 48)]
    required = []
    for sigma in (0.02, 0.05, 0.10, 0.15):
        for inflation in (1.0, 1.5, 2.0):
            n = next(n for n in range(12, 601, 6) if precision_scenario(n, sigma, variance_multiplier=inflation)[
                "probability_width_within_target_under_normal_independent_homoscedastic_model"] >= 0.8)
            required.append({"sigma": sigma, "variance_multiplier": inflation, "series_for_80percent_width_assurance": n})
    result = {"status": "planning_not_data_collection", "script_sha256": sha(Path(__file__)),
              "source_report_sha256": sha(source_path), "runtime": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__},
              "technical_estimand": "Equal mean over six maps of per-series log(mean graph_gru reconstruction loss / mean mlp_gru loss); average model seeds and windows inside series first.",
              "model": "One selected map per series, equal series counts per map; six fixed map means and independent Gaussian homoscedastic residuals. Residual df=n-6. Planning model only.",
              "width_target_log_units": 0.05, "confidence_level": 0.95, "assurance_target": 0.8,
              "descriptive_development_series_log_ratio_sd": float(old.std(ddof=1)),
              "development_sd_limit": "Only nine existing series, repeated teams and overlapping development fits; not a reliable population variance estimate or a post-hoc power calculation.",
              "scenarios": rows, "required_series_sensitivity": required,
              "limits": ["The 0.05 target is a planning resolution (~5.13% multiplicative ratio), not a justified threshold for tactical benefit.",
                         "Shared teams/events and heterogeneous variances can invalidate the independent common-variance model; variance multipliers are stress scenarios, not estimated ICC corrections.",
                         "Tactical relevance requires a separately designed judgment endpoint; this calculation cannot determine its sample size.",
                         "A feasible 12-series cohort does not guarantee a narrow interval or a publishable generalization claim; report realized uncertainty without effect-based sample extension."]}
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "report.json", result)
    print(json.dumps({"development_SD_descriptive": result["descriptive_development_series_log_ratio_sd"],
                      "baseline_n12_sigma005": precision_scenario(12, 0.05), "required_series": required}))


if __name__ == "__main__":
    main()
