# CS2 Silver Annotation v0.1

This dataset contains AI-assisted silver labels generated from deterministic demo facts and explicit weak-supervision rules. It is not presented as expert gold annotation.

## Coverage

- Matches: 20
- Demos: 49
- Maps: Ancient, Anubis, Cache, Dust2, Inferno, Mirage, Nuke
- Rounds: 1019
- Canonical events: 42148
- Labels: 5308
- Player ID coverage: 99.9%
- Actor team coverage: 100.0%
- Actor area coverage: 100.0%
- Bomb site coverage: 100.0%
- Mean label confidence: 0.996
- Missing evidence references: 0
- Duplicate event IDs: 0
- Tick boundary violations: 0

## Label distribution

| Label | Count |
|---|---:|
| EXECUTE_CANDIDATE | 146 |
| OPENING_DUEL | 1017 |
| POST_PLANT | 542 |
| RETAKE_CONTACT | 311 |
| TRADE_KILL | 1423 |
| UTILITY_BURST | 1869 |

## Method

- `OPENING_DUEL` and `POST_PLANT` are direct event facts; `TRADE_KILL` is a deterministic five-second temporal rule.
- `UTILITY_BURST` uses an eight-second same-team utility cluster followed by a kill or plant within ten seconds.
- `EXECUTE_CANDIDATE` is added only when a T-side utility burst is followed by a plant.
- `RETAKE_CONTACT` records the first post-plant CT-on-T kill and does not claim a complete retake strategy.
- Every label stores its rule version, confidence, review status, and evidence event IDs.

## Limitations

- EXECUTE_CANDIDATE is a weak-rule label, not tactical-intent ground truth.
- Bomb sites use the parser's place name; the numeric entity identifier is retained for audit.
- UTILITY_BURST and RETAKE_CONTACT describe temporal patterns, not tactical intent or success.
- No missed-trade label is produced without player trajectory and opportunity evidence.
