# Cross-map CT state prediction: manuscript evidence draft

Status: working Methods, Results and Limitations sections, not a submission-ready paper. Human annotation is paused at the user's request. These numerical results use previously observed development data. No tactical efficacy, coaching benefit or superiority of the original TAGNet task is established.

## Methods

We studied 465 eligible Counter-Strike 2 defensive-side opening windows from 22 Demos across nine series and six maps. Each window contains observations at 10, 12, 15, 18 and 20 seconds after freeze time. The shared eight-dimensional state comprises five live-region fractions, the dead-player fraction, and the mean and maximum live-pair Euclidean distances. Distances are divided by a fixed 5,000-game-unit scale. Undefined pair statistics are masked. Seventy-four windows contain casualties; these remain in prediction evaluation.

The original TAGNet study concerns snapshot reconstruction and unsupervised defensive-pattern discovery. Our next-state prediction task is an auxiliary representation probe. It is not a like-for-like reproduction of tactical clustering quality. The original fixed random temporal/context aggregation and our trained GRU variants must also be distinguished. Provenance is recorded in [TAGNet provenance](../TAGNET_PROVENANCE.md).

All train/validation/test partitions are separated by complete series. G2 trains map-specific shared-feature models; Anubis is omitted because only two series are available. G3 leaves one series out. G4 leaves out a map and removes every series containing that map from both training and validation. G5 adds one fixed target-map support series and tests on the remaining target series. Preprocessing and regularization selection use only training and validation data. Neural results average errors over seeds 0, 1 and 42, rather than selecting the most favorable seed.

The v14 exploratory comparison retains the exact G3/G4 folds, target masks, prediction constraints and seven ridge penalties from v7. The base model has ten current-frame features. Node summaries add ten role-conditioned live health/equipment sums and two live health/equipment standard deviations. Pair summaries add ten sorted live-pair distances and ten padding-validity indicators. Combined summaries contain 42 inputs and 344 fitted regression coefficients including intercepts. These summaries are permutation-invariant and use the same raw node/edge sources, but discard associations; they do not constitute a complete-information set-model control.

We report relative reductions in equal-series mean squared error. Paired series bootstrap intervals use 2,000 resamples and seed 20261023. They are conditional descriptive intervals: there are few series, teams overlap, and training folds overlap. The cohort has already been inspected, so none of these results are untouched confirmatory tests.

## Results

Table 1. v7 relative error reduction versus persistence (%); settings have different test subsets and must not be compared by subtracting rows.

| Setting | Test windows | Current ridge | Prefix ridge | Static graph | GRU |
|---|---:|---:|---:|---:|---:|
| G2 | 424 | 18.73 | 14.89 | 14.93 | 14.82 |
| G3 | 465 | 18.06 | 9.24 | 14.51 | 16.76 |
| G4 | 465 | 14.71 | 1.02 | 12.07 | 11.46 |
| G5 | 341 | 15.14 | 4.76 | 11.14 | 12.12 |

Current ridge was the strongest overall method in these four v7 settings. This does not establish that the original TAGNet clustering task is inferior to linear prediction. On the two newly acquired series alone in G1, the frozen static graph seed 42 slightly exceeded the frozen linear model (8.92% versus 8.24% reduction). That positive detail is retained; G1 also uses a different historical prediction-scoring convention.

Table 2. v14 fixed richer-summary controls: reduction versus persistence, followed by paired reduction versus the original ridge and its descriptive interval. Positive values favor the listed method.

| Setting | Control | Inputs | vs persistence (%) | vs ridge (%) | Descriptive interval vs ridge (%) |
|---|---|---:|---:|---:|---|
| G3 | ridge | 10 | 18.06 | 0.00 | [0.00, 0.00] |
| G3 | node_ridge | 22 | 17.66 | -0.48 | [-1.42, 0.25] |
| G3 | pair_ridge | 30 | 17.75 | -0.38 | [-1.75, 0.60] |
| G3 | pooled_ridge | 42 | 18.24 | 0.23 | [-0.50, 0.85] |
| G4 | ridge | 10 | 14.71 | 0.00 | [0.00, 0.00] |
| G4 | node_ridge | 22 | 14.19 | -0.61 | [-1.29, 0.10] |
| G4 | pair_ridge | 30 | 14.60 | -0.13 | [-0.91, 0.63] |
| G4 | pooled_ridge | 42 | 14.01 | -0.82 | [-2.30, 0.50] |

The combined summary yields only a 0.23% paired reduction relative to ridge in G3, with an interval spanning zero. In G4 it increases error by 0.82%, again with an interval spanning zero. Neither added group alone gives a consistent improvement. These results do not support adopting the richer summaries as a superior model; all four conditions remain reported. The reproduced base-ridge forecasts differ from the saved v7 predictions by at most 7.78e-16.

Table 3. Failures and constraints that accompany the aggregate results.

| Observation | Evidence | Consequence |
|---|---|---|
| Coarse state dominates improvement | G4 ridge region/death components improve 15.26%, distances only 1.62% | Do not infer learned navigation or tactical intent |
| More history is not uniformly helpful | G4 prefix ridge improves only 1.02% versus persistence | A longer prefix is not automatically better transfer |
| A neural component can degrade | G4 GRU death-count error increases about 2.32% versus persistence | Report per-component failures |
| Map vocabularies lose detail | About 49–79% of live occupancy is mapped to other across maps | Static role/route semantics remain unresolved |
| Geometry retrieval is a proxy | Five-frame top-5 geometric MSE: common 0.008440, static 0.015095, GRU 0.015512 | Do not call this tactical relevance |

## Limitations and work remaining

No independent tactical endpoint is established. Human responses and developer-involved AI silver judgments are separate pilot evidence and are not used for this experiment. Their workstream is paused. The geometric retrieval diagnostic uses the original frozen encoders and a Dust2 training library, not the newly cross-validated encoders. Shared teams and the small number of series prevent population-level conclusions. Target-map static geometry access must be disclosed when future map semantics are evaluated; historical patch compatibility is not fully established.

The next missing model control is an information-matched trainable set or pair-set model; the pooled ridge summaries do not fill that gap. New semantic roles, navigable distances and clustering claims also require separate evidence. A new untouched test cohort should be collected only after the recipe, primary comparison, sampling budget and stopping rule are fixed. Original-task reconstruction/clustering reproduction remains a separate track. Related work, publication novelty, statistical power and submission requirements need separate verification before manuscript completion.

## Reproducibility pointers

- [v7 numerical report](../../datasets/evaluation/ct_grouped_v7_report.json)
- [v14 fixed development recipe](../../datasets/selections/ct_pooled_ridge_v14.json)
- [v14 results and artifact receipts](../../datasets/evaluation/ct_pooled_ridge_v14_report.json)
- [Run script](../../scripts/evaluate_ct_pooled_ridge.py)
- Only two targeted synthetic tests were run for the new summaries: permutation/causality and missing-pair/invalid-distance handling. Full regression and GPU retraining were not repeated.
- v14 used no new Demos or GPU; elapsed fitting/evaluation was approximately 1.58 seconds, with process peak working set approximately 56.37 MiB. RAM guards require 2 GiB at start and 1.5 GiB during fitting. Raw Demos, weights and map images remain local and are not bundled for redistribution.
