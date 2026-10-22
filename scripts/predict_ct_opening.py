"""Run the small experimental CT forecast on extracted snapshots, without GPU or ingestion."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_linear_service import CTLinearPredictor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=ROOT / "datasets/models/ct_linear_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    model = CTLinearPredictor(args.model)
    document = json.loads(args.snapshots.read_text(encoding="utf-8"))
    report = {"status": "experimental_CT_state_forecasts", "map": document["map_name"],
              "source_demo_sha256": document["source_demo_sha256"], "rounds": [], "skipped": []}
    for row in document["rounds"]:
        if row["side"] != "CT":
            continue
        if row["status"] != "ok":
            report["skipped"].append({"round": row["round_number"], "reason": row["reason"]})
            continue
        report["rounds"].append({"round_number": row["round_number"], "side": "CT", **model.predict(row["snapshots"])})
    if not report["rounds"]:
        parser.error("No eligible CT rounds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"rounds": len(report["rounds"]), "skipped": len(report["skipped"]),
                      "model_version": model.model_version, "model_sha256": model.sha256}))


if __name__ == "__main__":
    main()
