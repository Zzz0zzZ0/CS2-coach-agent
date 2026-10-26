"""CPU numerical replay of cached losses; no model, Demo, or human data required."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
from scipy.stats import t

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = ('mlp_static', 'mlp_gru', 'graph_static', 'graph_gru',
              'graph_gru_no_motion', 'graph_gru_common')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def primary_interval(rows):
    """Standalone reference calculation; frozen inference code remains unchanged."""
    if len(rows) != 12 or len({r['series'] for r in rows}) != 12:
        raise ValueError('Twelve distinct series required')
    maps = sorted({r['map'] for r in rows})
    if len(maps) != 6:
        raise ValueError('Six maps required')
    groups = []
    for name in maps:
        losses = np.asarray([[r['graph_gru'], r['mlp_gru']] for r in rows if r['map'] == name])
        if losses.shape != (2, 2) or not np.isfinite(losses).all() or (losses <= 0).any():
            raise ValueError('Two finite positive paired series losses per map required')
        groups.append(np.log(losses[:, 0] / losses[:, 1]))
    variances = np.asarray([g.var(ddof=1) for g in groups])
    estimate = float(np.mean([g.mean() for g in groups]))
    se = float(np.sqrt(variances.sum() / 72))
    pooled_half = float(t.ppf(.975, 6) * se)
    contributions = variances / 2
    welch_df = float(contributions.sum() ** 2 / (contributions ** 2).sum()) if contributions.sum() else None
    welch_half = float(t.ppf(.975, welch_df) * se) if welch_df else 0.
    return {'log_ratio': estimate, 'geometric_loss_ratio': float(np.exp(estimate)), 'SE': se,
            'pooled_df': 6, 'pooled_log_CI95': [estimate - pooled_half, estimate + pooled_half],
            'pooled_ratio_CI95': np.exp([estimate - pooled_half, estimate + pooled_half]).tolist(),
            'Welch_Satterthwaite_df': welch_df,
            'heteroscedastic_log_CI95': [estimate - welch_half, estimate + welch_half]}


def verify_manifest(root):
    root = Path(root).resolve()
    path = root / 'bundle_manifest.json'
    if not path.exists():
        return False
    for row in json.loads(path.read_text(encoding='utf-8'))['files']:
        candidate = (root / row['path']).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file() or digest(candidate) != row['sha256']:
            raise ValueError('Bundle integrity failure: ' + row['path'])
    return True


def replay(root):
    root = Path(root).resolve()
    manifest_checked = verify_manifest(root)
    report_path = root / 'datasets/evaluation/ct_independent_confirmation_report.json'
    expected = json.loads(report_path.read_text(encoding='utf-8'))
    protocol_path = root / 'datasets/selections/ct_independent_confirmation.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    if digest(protocol_path) != expected['protocol_sha256']:
        raise ValueError('Frozen protocol differs')
    predictions = root / 'output/tagnet/ct_independent_confirmation'
    for name, checksum in expected['artifacts_sha256'].items():
        path = (predictions / name).resolve()
        if path.parent != predictions.resolve() or digest(path) != checksum:
            raise ValueError('Frozen prediction artifact differs: ' + name)
    per_seed = []
    for map_name in sorted({r['map'] for r in expected['per_series']}):
        index = json.loads((predictions / (map_name + '_index.json')).read_text(encoding='utf-8'))
        for condition in CONDITIONS:
            for seed in protocol['seeds']:
                with np.load(predictions / f'{map_name}_{condition}_{seed}.npz', allow_pickle=False) as data:
                    loss, components = data['loss'], data['components']
                    if loss.shape != (len(index),) or components.shape != (len(index), 7):
                        raise ValueError('Prediction shape mismatch')
                    if not np.isfinite(loss).all() or not np.isfinite(components).all():
                        raise ValueError('Nonfinite prediction loss')
                    for series in sorted({r['series'] for r in index}):
                        selected = np.asarray([r['series'] == series for r in index])
                        per_seed.append({'series': series, 'map': map_name, 'condition': condition, 'seed': seed,
                                         'windows': int(selected.sum()), 'loss': float(loss[selected].mean()),
                                         'components': components[selected].mean(0).tolist()})
    key = lambda r: (r['series'], r['condition'], r['seed'])
    expected_seed = {key(r): r for r in expected['per_seed_series']}
    if set(map(key, per_seed)) != set(expected_seed):
        raise ValueError('Series/condition/seed coverage differs')
    for row in per_seed:
        reference = expected_seed[key(row)]
        assert row['map'] == reference['map'] and row['windows'] == reference['windows']
        np.testing.assert_allclose(row['loss'], reference['loss'], atol=1e-10, rtol=0)
        np.testing.assert_allclose(row['components'], reference['components'], atol=1e-10, rtol=0)
    series_rows = []
    for series in sorted({r['series'] for r in per_seed}):
        rows = [r for r in per_seed if r['series'] == series]
        series_rows.append({'series': series, 'map': rows[0]['map'], 'windows': rows[0]['windows'],
                            **{condition: float(np.mean([r['loss'] for r in rows if r['condition'] == condition]))
                               for condition in CONDITIONS}})
    reference_series = {r['series']: r for r in expected['per_series']}
    for row in series_rows:
        for condition in CONDITIONS:
            np.testing.assert_allclose(row[condition], reference_series[row['series']][condition], atol=1e-10, rtol=0)
    interval = primary_interval(series_rows)
    for name, value in interval.items():
        np.testing.assert_allclose(value, expected['primary'][name], atol=1e-10, rtol=0)
    return {'status': 'pass_cached_loss_metric_replay', 'bundle_integrity_checked': manifest_checked,
            'windows': sum(r['windows'] for r in series_rows), 'series': len(series_rows),
            'prediction_files': len(CONDITIONS) * len(protocol['seeds']) * 6,
            'series_condition_seed_rows': len(per_seed), 'primary': interval,
            'heteroscedastic_ratio_CI95': np.exp(interval['heteroscedastic_log_CI95']).tolist(),
            'maximum_comparison_absolute_tolerance': 1e-10,
            'scope': 'Aggregation from cached losses, not fresh model inference, training, raw-Demo parsing or semantic validation.'}


def build_bundle(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    expected = json.loads((root / 'datasets/evaluation/ct_independent_confirmation_report.json').read_text(encoding='utf-8'))
    names = ['LICENSE', 'scripts/replay_ct_confirmation.py', 'scripts/evaluate_ct_independent_confirmation.py',
             'docs/paper/NUMERICAL_REPLAY.md', 'docs/paper/replay-requirements.txt',
             'datasets/evaluation/ct_independent_confirmation_report.json',
             'datasets/evaluation/ct_paper_environment.json', 'datasets/evaluation/ct_manuscript_cohort_summary.json',
             'datasets/selections/ct_independent_confirmation.json', 'datasets/selections/ct_independent_analysis.json']
    names += ['output/tagnet/ct_independent_confirmation/' + name for name in expected['artifacts_sha256']]
    names += ['output/tagnet/ct_independent_confirmation/' + name + '_index.json'
              for name in sorted({r['map'] for r in expected['per_series']})]
    manifest = {'status': 'local_reference_only_pending_rights_and_anonymity_review',
                'scope': 'Recompute main per-series losses and both intervals from frozen prediction arrays.',
                'excluded': ['raw Demos', 'human returns', 'silver labels', 'credentials', 'model weights', 'training inputs'],
                'files': []}
    for name in sorted(names):
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Unexpected bundle input: ' + name)
        manifest['files'].append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for row in manifest['files']:
            archive.write(root / row['path'], row['path'])
        archive.writestr('bundle_manifest.json', json.dumps(manifest, indent=2) + '\n')
    return {'bundle_path': destination.relative_to(root).as_posix(), 'bundle_sha256': digest(destination),
            'bytes': destination.stat().st_size, 'files': len(manifest['files']),
            'uncompressed_bytes': sum(r['bytes'] for r in manifest['files']), 'redistribution_approved': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--bundle', type=Path, help='Create a new local reference ZIP after replay succeeds')
    parser.add_argument('--output', type=Path, help='Write a new replay receipt')
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error('Output receipt exists')
    result = replay(args.root)
    if args.bundle:
        result['bundle'] = build_bundle(args.root, args.bundle)
    encoded = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(encoded)
    print(encoded)


if __name__ == '__main__':
    main()
