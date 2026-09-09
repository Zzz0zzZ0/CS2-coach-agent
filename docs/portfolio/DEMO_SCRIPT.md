# Three-minute local demo

Open the existing console at `http://localhost:5173`. The API is on port 8001; retrieval and profile demonstrations below do not require a provider call. Do not upload a demo or change a key just to show retrieval.

| Time | Action | Explanation |
| --- | --- | --- |
| 0:00–0:35 | Select a player, inspect the sample scope and behavior groups. | The denominator is roster participation; the sample is limited to recorded series. |
| 0:35–1:10 | Ask `Match 2396949, map Nuke. Round win rate when donk trades teammate zont1x within 320 ticks` | One matched round among 21 checked, one known win; the 100% figure describes one observation, not skill. Open its evidence timeline. |
| 1:10–1:35 | Ask `比赛 2396949，地图 Nuke。回合胜率：TeSeS 击杀 tN1R，发生在下包之后` | Zero matches within this complete scope; no win-rate denominator. |
| 1:35–1:55 | Ask `Match 2396949, map Nuke. donk trades teammate zont1x within 5 seconds` | Unsupported units remain explicit; the system does not silently assume a tick rate. |
| 1:55–2:35 | Open `benchmark-results.svg`. | Compare development and isolated observed-series results; explain model/fusion failures and AI label limitations. |
| 2:35–3:00 | Show the linked frozen protocols, CI and case study. | Explain rollback, source audits and the remaining independent evaluation work. |

The samples above were checked against the current graph. If a future graph changes, rerun the cited checks before presenting. Never describe this scripted demonstration as an independent benchmark.

## Optional engineering walkthrough

Open the saved local task `http://localhost:5173/?task_id=b0171fbf-18c5-4aa1-ad0b-a052ab52169e` without uploading another file. Show its actual 20 execution events, expand the four report-consistency checks, then select the opening-loss question and inspect C3/R2. Ask for R999 to demonstrate a scoped absence. This path is read-only and makes no model calls. Explain that verification reuses normalized event computation and fixed report templates; it does not establish independent factual truth or coaching quality. See [acceptance and limits](../REPORT_QUESTIONS_V1.md).
