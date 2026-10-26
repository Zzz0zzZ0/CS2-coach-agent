# Local numerical reference bundle

This bundle recomputes the main independent-cohort numbers from the frozen per-window loss arrays. It checks all 108 prediction archives, 216 series/condition/seed rows, twelve series summaries, the equal-map log ratio, and both conditional intervals against the recorded report.

It does not rerun a model, reconstruct losses from decoder predictions, retrain a model, parse a Demo, reproduce human judgments, or validate tactical relevance. It is a numerical aggregation replay. The complete inference/training routes and access limits are described in `docs/paper/REPRODUCIBILITY.md` in the project.

## Run after extracting

Use Python 3.11 or newer. Install the two dependencies in `docs/paper/replay-requirements.txt`, then run from the extracted root:

```text
python scripts/replay_ct_confirmation.py --root . --output replay.json
```

The script verifies every file against `bundle_manifest.json`, checks each prediction archive against the original report, and refuses to overwrite an output receipt. All numerical comparisons use absolute tolerance 1e-10. The cached float32 per-series means are computed before the across-seed average, as in the frozen evaluator.

The standalone interval implementation is checked against the frozen evaluator in the repository test suite. Its independent-normal-series and variance assumptions remain unchanged. The pooled and unequal-variance intervals are conditional model calculations; repeated teams and events remain limitations.

## Access and rights

This is a local reference artifact pending the authors' rights and anonymity review. It is not approved for redistribution or anonymous submission. The software license does not establish rights to underlying game recordings or their derived outputs.

The bundle excludes raw Demos, human returns, silver labels, credentials, model weights and training inputs. Series IDs and provenance remain in its metadata; it is not an anonymized review package. The frozen evaluator source is included for comparison, while only the standalone replay script is executable with the two listed dependencies.
