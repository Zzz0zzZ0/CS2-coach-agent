import json
import numpy as np
import pytest
from scripts.replay_ct_confirmation import primary_interval, verify_manifest
from scripts.evaluate_ct_independent_confirmation import confirmation_interval


def test_standalone_intervals_match_frozen_evaluator():
    rows = [{'series': str(i), 'map': str(i // 2), 'graph_gru': .1 + i * .001, 'mlp_gru': .12 + i * .002}
            for i in range(12)]
    expected = confirmation_interval(rows)
    for key, value in primary_interval(rows).items():
        np.testing.assert_allclose(value, expected[key], atol=1e-14, rtol=0)
    rows[-1]['series'] = rows[0]['series']
    with pytest.raises(ValueError, match='distinct'):
        primary_interval(rows)


def test_reference_bundle_rejects_changed_bytes_and_path_escape(tmp_path):
    path = tmp_path / 'bundle_manifest.json'
    (tmp_path / 'loss.json').write_text('{}', encoding='utf-8')
    for name in ('loss.json', '../outside.json'):
        path.write_text(json.dumps({'files': [{'path': name, 'sha256': '0' * 64}]}), encoding='utf-8')
        with pytest.raises(ValueError, match='integrity'):
            verify_manifest(tmp_path)
