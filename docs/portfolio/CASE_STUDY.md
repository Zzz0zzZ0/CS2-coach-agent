# CS2 Coach Agent — evidence before advice

An applied AI engineering project for converting professional Counter-Strike 2 demos into traceable player analysis and bounded coaching suggestions. Built with Python, FastAPI, Celery/Redis, SQLite, Milvus, LangGraph and React, with AI-assisted development and explicitly identified AI-assisted source audits.

## The problem

A fluent tactical explanation is easy to generate and difficult to trust. Player statistics can have the wrong denominator; a retrieved round can mention both players without proving the requested interaction; a plausible coaching recommendation can exceed what the recorded events establish.

The project addresses these failure modes through an auditable data pipeline, source-grounded retrieval and a restricted model output contract.

## What the implementation demonstrates

- **Data integrity:** 20 historical series, 49 maps, 1,019 regulation/overtime rounds and 56 player profiles. A later parser audit found four pre-match knife rounds; the graph and derived indexes were rebuilt with old snapshots preserved. Complete roster participation supplies denominators, including players with no recorded action in a round.
- **Traceable retrieval:** map, match and player scopes lead to round timelines and original event IDs. A bounded bilingual relation query path verifies directed opening kills, kills after a plant and same-enemy trade kills before truncating results. It distinguishes verified absence from incomplete information and unsupported conditions.
- **Reliable aggregation:** conditional counts use the full scanned scope, not the displayed top-k. Unknown outcomes are excluded from win-rate denominators and shown explicitly. Descriptive associations are not presented as individual contribution or causal effects.
- **Operational safeguards:** offline CI, locked dependencies, durable model-call reservations, failure states and recoverable Git checkpoints. The fixed `qwen3.8-flash` step selects priorities from an allowlist; deterministic code owns report facts. Automated knowledge ingestion remains disabled by default.
- **Measured optimization:** a small player-scope filter preserved all 224 full outputs in a 56-player / four-filter comparison while reducing local median function latency from 335 ms to 104 ms. This is a single interleaved warm-cache measurement, not a throughput claim.

## Evaluation that changed the design

![Development retrieval results](benchmark-results.svg)

The important finding was not that every new component improved retrieval. On historical relation development questions, a second bilingual dense setup improved paired nDCG@5 from 0.1476 to 0.3148. On an isolated pilot using two previously observed series, the scores were 0.2028 and 0.2213; the preferred model differed by series. RRF did not consistently beat dense retrieval, and every uncalibrated top-k text pipeline still returned results for unanswerable relation questions.

This motivated a separate deterministic relation verifier. On the isolated source-selected pilot it passed 60 bilingual expressions and 780 integration/evidence checks, with 15 unanswerable semantic groups correctly returning no relation evidence. These results validate a restricted query contract; they are not an independent generalization result or an improvement to RRF.

| Evidence | Scope | Supported interpretation |
| --- | --- | --- |
| 269 offline tests | Synthetic and engineering regressions | Tested implementation behavior |
| 48 relation expressions + 96 aggregate checks | Observed historical questions | Relation / numeric contract consistency |
| 768 text retrieval results | Historical development controls | Model, tokenizer and fusion tradeoffs |
| 960 text results + 60 relation expressions | Two isolated, previously observed series | Corpus-isolated development pilot |
| Two consecutive live browser uploads, 2,325 model tokens | One observed 14-round map, one persistent worker | Complete application integration and post-fix TLS lifecycle regression; no coaching-quality claim |
| 6 Coach model calls, 4,939 reported tokens | Six development maps | Feasibility and per-run usage; quality gain unscored |

Labels and translations are AI-assisted. Python and SQL audits share parser facts. The two isolated series are not newly unseen data, and independent expert coaching ratings are deferred as optional future research, outside the current engineering and portfolio delivery scope. The dense models also have different actual chunk capacities (128 vs 512 tokens), so the comparison concerns whole configurations.

## A useful research question

Under what conditions should an analyst system answer from ranked text, execute a structured event query, or abstain? This project provides a small, reproducible setting for studying that choice, with observable actors, temporal predicates and evidence provenance. A future study would freeze new complete series and natural question distributions, independently audit labels, calibrate abstention on development data, and evaluate expert utility without exposing method identities.

The current project is an engineering prototype with credible development evidence. It does not establish improved player performance, professional coaching quality or broad out-of-distribution generalization.

## Review the evidence

- [Data correction and rollback](../HISTORICAL_DATA_REBUILD_V2.md)
- [Relation and aggregate contracts](../RELATION_QUERY_ENGINE_V2.md)
- [Bilingual baseline experiment](../LANGUAGE_BASELINES_V2.md)
- [Isolated pilot and first-run failures](../ISOLATED_RELATION_PILOT_V1.md)
- [Player performance equivalence](../PLAYER_PERFORMANCE_V1.md)
- [Live upload acceptance and failure record](../LIVE_E2E_V2.md)
- [Main implementation and execution status](../IMPLEMENTATION_PROGRESS.md)
- [Exportable figure](benchmark-results.svg) · [PNG](benchmark-results.png) · [plotted data](benchmark-results.csv)
