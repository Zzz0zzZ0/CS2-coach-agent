"""Frozen CT expansion: serial demo extraction, timing audit, prediction and representation export."""

import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.ct_evaluation_service import error_totals, summarize, paired_series_bootstrap
from app.services.ct_feature_service import feature_sequence
from app.services.ct_linear_service import CTLinearPredictor, linear_inputs, linear_forecast
from app.services.opening_timing_service import CLOCK_PROPERTIES, audit_opening_timing, round_wins_from_rosters
from app.services.parser_service import TacticalDemoParser
from app.services.team_identity_service import canonical_team
from scripts.ct_experiment_data import load_source


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_input_manifest(path, protocol):
    rows = json.loads(path.read_text(encoding="utf-8"))["files"]
    files = [(str(row["series"]), Path(row["demo_path"]).resolve()) for row in rows]
    expected = {str(row["match_id"]) for row in protocol["matches"]}
    if not files or len(files) > protocol["limits"]["new_demos_max"] or {s for s, _ in files} != expected:
        raise ValueError("Input manifest must cover exactly the selected series within the demo limit")
    if len({p for _, p in files}) != len(files) or any(not p.is_file() or p.suffix.lower() != ".dem" for _, p in files):
        raise ValueError("Distinct existing demo files required")
    for row, (_, demo) in zip(rows, files):
        if sha(demo) != row["sha256"]:
            raise ValueError("Input demo checksum mismatch")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=ROOT / "datasets/selections/ct_expansion_v3.json")
    parser.add_argument("--upstream-dir", type=Path, default=ROOT / "output/tagnet/upstream")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, help="Evaluate only these selected, checksummed demos")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Use a new output directory")
    protocol = json.loads(args.protocol.read_text())

    def check_freeze():
        for path, digest in protocol["frozen_sha256"].items():
            assert sha(ROOT / path) == digest, f"Frozen input changed: {path}"
    check_freeze()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = args.upstream_dir / "data/processed/dust2_ct_5snap/ct_snapshot_nodes.parquet"
    source_groups, source_audit = load_source(source)
    write(args.output_dir / "source_audit.json", {"source_sha256": sha(source), **source_audit})
    assert not source_audit["exact_cross_split_duplicate_groups"], "Source content leakage detected"
    groups = {"source_train": source_groups["train"], "dust2_test": source_groups["test"]}
    metadata = {"source_train": {"scope": "candidate_library_only"}, "dust2_test": {"scope": "published_development"}}
    matches = {row["match_id"]: row for row in protocol["matches"]}
    if args.input_manifest:
        files = read_input_manifest(args.input_manifest, protocol)
    else:
        original = Path("E:/iem-cologne-major-2026-furia-vs-falcons-bo5-KYwh5Z9rwDlzjmTFrwu0mb")
        files = [("furia_falcons_existing_local", p) for p in sorted(original.glob("*.dem"))]
        for series, directory in (("2396940", "new_demos_2396940"), ("2396949", "new_demos_2396949")):
            files.extend((series, p) for p in sorted((ROOT / "output/tagnet" / directory).glob("*.dem")))
        new_dir = ROOT / "output/tagnet/new_demos_expansion_v3"
        new_files = sorted(new_dir.glob("*.dem"))
        assert len(new_files) == 5
        files.extend((next(s for s in matches if s in p.name), p) for p in new_files)
        assert len(files) == 12
    acquisition = []
    for series, path in files:
        assert psutil.virtual_memory().available > 2 * 2**30, "RAM guard before demo parse"
        loaded = TacticalDemoParser(str(path))
        observed = loaded.parse_opening_snapshots()
        map_name = observed["map_name"]
        name = f"{series}__{map_name}"
        assert name not in groups, "Duplicate map-series input"
        digest = sha(path)
        observed.update(source_demo=path.name, source_demo_sha256=digest)
        write(args.output_dir / f"{name}_snapshots.json", observed)
        clock_ticks = sorted({row["freeze_end_tick"] + second * 64 for row in observed["rounds"]
                              if row["side"] == "CT" and row["status"] == "ok" for second in range(21)})
        clock = loaded.parser.parse_ticks(CLOCK_PROPERTIES, ticks=clock_ticks)
        timing = audit_opening_timing(observed["rounds"], clock)
        write(args.output_dir / f"{name}_timing.json", timing)
        passed = {row["round_number"] for row in timing["rounds"] if row["passed"]}
        skipped, records = [], []
        for row in observed["rounds"]:
            if row["side"] != "CT":
                continue
            if row["status"] != "ok":
                skipped.append({"round": row["round_number"], "reason": row["reason"]}); continue
            try:
                features = feature_sequence(row["snapshots"])
            except ValueError as error:
                skipped.append({"round": row["round_number"], "reason": str(error)}); continue
            records.append({"id": f"{digest}:{row['round_number']}:CT", "series": series, "map": map_name,
                            "round_number": row["round_number"], "timing_passed": row["round_number"] in passed,
                            "features": features})
        assert records, f"No CT samples: {name}"
        groups[name] = records
        ends, boundary = loaded._completed_rounds()
        wins = round_wins_from_rosters(ends["winner"], loaded.parse_round_rosters(ends, start_tick=boundary))
        expected = matches.get(series, {}).get("public_map_scores", {}).get(map_name.removeprefix("de_").title())
        # Dust2/Mirage title casing matches the frozen selection; all score checks are independent of predictions.
        if map_name == "de_dust2":
            expected = matches.get(series, {}).get("public_map_scores", {}).get("Dust2")
        canonical = canonical_team
        score_match = ({canonical(k): v for k, v in wins.items()} == {canonical(k): v for k, v in expected.items()}) if expected else None
        selected = matches.get(series)
        native_teams = {canonical(row["team"]) for row in observed["rounds"] if row.get("team")}
        teams_match = native_teams == {canonical(selected["team1"]), canonical(selected["team2"])} if selected else None
        prior_rounds = selected.get("expected_prior_round_totals", {}).get(map_name.removeprefix("de_").title()) if selected else None
        if selected and map_name == "de_dust2":
            prior_rounds = selected.get("expected_prior_round_totals", {}).get("Dust2")
        metadata[name] = {"series": series, "map": map_name, "rounds": len(records), "skipped": skipped,
            "scope": "frozen_new_acquisition" if series in matches else "unobserved_map_existing_series" if map_name == "de_nuke" else "retrospective_development",
            "timing_passed": sum(r["timing_passed"] for r in records), "timing_failures": [r for r in timing["rounds"] if not r["passed"]],
            "engine_rounds": len(ends), "engine_wins": dict(wins), "expected_public_score": expected, "public_score_matches": score_match,
            "teams_match_selection": teams_match, "expected_prior_rounds": prior_rounds,
            "prior_round_count_matches": len(ends) == prior_rounds if prior_rounds is not None else None,
            "other_region_fraction": float(np.mean([r["features"]["targets"][:, 4].mean() for r in records]))}
        acquisition.append({"series": series, "file": path.name, "map": map_name, "sha256": digest, "bytes": path.stat().st_size})
        write(args.output_dir / "input_manifest.json", {"files": acquisition, "groups": metadata})
        assert teams_match is not False, f"Native teams do not match selected series: {name}"
        print(json.dumps({"parsed": name, "rounds": len(records), "timing_passed": metadata[name]["timing_passed"],
                          "public_score_matches": score_match}), flush=True)
        del loaded, observed, clock

    import torch
    from run_ct_generalization import CTModel, batch, arrays
    assert torch.cuda.is_available()
    torch.set_num_threads(1)
    torch.cuda.set_per_process_memory_fraction(.2)
    assert torch.cuda.mem_get_info()[0] > 1024 * 2**20
    torch.backends.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.rnn.fp32_precision = "tf32"
    sys.path.insert(0, str(args.upstream_dir / "scripts"))
    import train_tagnet as trainer
    data = {name: arrays(rows) for name, rows in groups.items()}
    outputs, representations = {}, {}
    for name, values in data.items():
        if name != "source_train":
            outputs[name] = {"persistence": values["targets"][:, :-1]}
    linear = CTLinearPredictor(ROOT / "datasets/models/ct_linear_v1.json")
    for name, values in data.items():
        inputs, current = linear_inputs(values)
        if name != "source_train":
            outputs[name]["ct_linear_v1"] = linear_forecast(inputs[:, :-1], current[:, :-1], linear.mean, linear.std, linear.coefficients)
        representations[f"{name}__common"] = current.reshape(len(current), -1)
    for path in sorted((ROOT / "output/tagnet/ct_generalization_residual_v1").glob("*.pt")):
        assert psutil.virtual_memory().available > 1536 * 2**20
        checkpoint = torch.load(path, weights_only=True, map_location="cpu")
        model = CTModel(trainer, residual=True)
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
        model = model.cuda().eval().requires_grad_(False)
        with torch.no_grad():
            for name, values in data.items():
                preds, embeddings = [], []
                for start in range(0, len(values["nodes"]), 64):
                    inputs = {k: v for k, v in batch(values, start, start + 64).items() if k in ("nodes", "edges", "alive")}
                    _, pred, embedding = model(inputs, checkpoint["temporal"])
                    preds.append(pred.cpu().numpy()); embeddings.append(embedding.cpu().numpy())
                if name != "source_train":
                    outputs[name][path.stem] = np.concatenate(preds)
                if checkpoint["seed"] == 42:
                    representations[f"{name}__{path.stem}"] = np.concatenate(embeddings)
        del model
        print(json.dumps({"evaluated": path.stem}), flush=True)
    np.savez_compressed(args.output_dir / "representations.npz", **representations)
    np.savez_compressed(args.output_dir / "predictions.npz", **{f"{name}__{model}": pred for name, models in outputs.items() for model, pred in models.items()})
    write(args.output_dir / "sample_index.json", {name: [{k: v for k, v in row.items() if k != "features"} for row in rows] for name, rows in groups.items()})
    report = {"status": "frozen_expansion_completed", "protocol_sha256": sha(args.protocol), "frozen_sha256": protocol["frozen_sha256"],
              "evaluator_sha256": sha(Path(__file__)),
              "helper_sha256": {str(p.relative_to(ROOT)): sha(p) for p in [ROOT / "app/services/opening_timing_service.py", ROOT / "app/services/ct_evaluation_service.py", ROOT / "scripts/ct_experiment_data.py", ROOT / "app/services/team_identity_service.py"]},
              "input_selection_sha256": sha(args.input_manifest) if args.input_manifest else None,
              "source_audit": source_audit, "acquisition": acquisition, "groups": metadata,
              "metrics": {}, "paired_series": {}, "limitations": ["only two newly acquired series; known in older project manifests",
              "source alias risk unresolved", "uncertainty intervals descriptive with few series", "no human tactical relevance judgments"]}
    totals = {}
    for name, models in outputs.items():
        values = data[name]
        report["metrics"][name] = {}
        totals[name] = {}
        for label, prediction in models.items():
            per_round = [error_totals(p, t, mask) for p, t, mask in zip(prediction, values["targets"][:, 1:], values["target_mask"][:, 1:])]
            totals[name][label] = per_round
            strict = [row for row, record in zip(per_round, groups[name]) if record.get("timing_passed")]
            report["metrics"][name][label] = {"all": summarize(per_round), "timing_strict": summarize(strict),
                "any_death_in_window": summarize([row for row, record in zip(per_round, groups[name]) if (~record["features"]["alive"]).any()])}
    for scope in ("new_series_only", "all_target_series"):
        selected = [name for name in outputs if name != "dust2_test" and (scope == "all_target_series" or metadata[name]["series"] in matches)]
        report["paired_series"][scope] = {}
        for label in next(iter(outputs.values())):
            if label == "persistence":
                continue
            model_rows, baseline_rows, series = [], [], []
            for name in selected:
                model_rows.extend(totals[name][label]); baseline_rows.extend(totals[name]["persistence"])
                series.extend([metadata[name]["series"]] * len(groups[name]))
            report["paired_series"][scope][label] = paired_series_bootstrap(model_rows, baseline_rows, series)
    report["resources"] = {"peak_allocated_VRAM_MiB": torch.cuda.max_memory_allocated() / 2**20,
                           "process_RSS_MiB": psutil.Process().memory_info().rss / 2**20}
    check_freeze()
    write(args.output_dir / "report.json", report)
    print(json.dumps({"completed": str(args.output_dir), "series": len(set(r["series"] for r in acquisition)),
                      "maps": len(set(r["map"] for r in acquisition)), "target_CT_rounds": sum(len(v) for k, v in groups.items() if k not in ("source_train", "dust2_test"))}), flush=True)


if __name__ == "__main__":
    main()
