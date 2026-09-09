"""Read-only response-size and exact-output comparison on an existing saved match."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from app.services.analysis_runs import AnalysisRunStore
from app.services.followup_service import answer_question
from app.services.metrics_service import calculate_metrics


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def run(task_id, baseline_source):
    store = AnalysisRunStore()
    before = hashlib.sha256(store.path.read_bytes()).hexdigest()
    saved = store.read_input(task_id)
    match = json.loads(saved['input_json'])
    metrics = calculate_metrics(match['rounds'])
    spec = importlib.util.spec_from_file_location('followup_baseline', baseline_source)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    rows = []
    cases = [('opening_losses', {}), ('post_plant_losses', {}),
             ('round', {'round_number': match['rounds'][0]['round_number']}),
             ('player', {'player': next(iter(metrics['players']))})]
    for kind, params in cases:
        old = baseline.answer_question(store, task_id, kind, **params)
        full = answer_question(store, task_id, kind, **params)
        assert full == old, f'Full response changed: {kind}'
        compact = answer_question(store, task_id, kind, **params, detail='compact')
        round_responses = [answer_question(store, task_id, 'round', round_number=s['metadata']['round_number'],
            expected_payload_sha256=full['provenance']['payload_sha256']) for s in full['sources']]
        for source, detail in zip(full['sources'], round_responses):
            assert detail['sources'] == [source]
        # Direct round questions already return full detail in the UI.
        initial_size = size(full) if kind == 'round' else size(compact)
        expanded_size = initial_size if kind == 'round' else initial_size + sum(map(size, round_responses))
        rows.append({'kind': kind, 'params': params, 'sources': len(full['sources']),
                     'default_full_equal_to_baseline': True, 'expanded_sources_equal': True,
                     'full_bytes': size(full), 'compact_bytes': size(compact), 'ui_initial_bytes': initial_size,
                     'ui_initial_reduction_pct': round(100 * (1 - initial_size / size(full)), 2),
                     'ui_all_expanded_bytes': expanded_size,
                     'ui_extra_requests_if_all_expanded': 0 if kind == 'round' else len(round_responses)})
    assert before == hashlib.sha256(store.path.read_bytes()).hexdigest(), 'Saved history changed'
    return {'task_id': task_id, 'payload_sha256': json.loads(saved['metadata'])['payload_sha256'],
            'baseline_source_sha256': hashlib.sha256(baseline_source.read_bytes()).hexdigest(),
            'saved_history_unchanged': True, 'remote_model_calls': 0, 'cases': rows,
            'interpretation': 'Uncompressed JSON body bytes on one observed match; not total page traffic, '
                              'latency, memory, token savings or a generalization benchmark. '
                              'Expanding every list source increases total requests and body bytes.'}


if __name__ == '__main__':
    import socket
    def denied(*args, **kwargs):
        raise RuntimeError('This comparison is offline')
    socket.socket.connect = socket.socket.connect_ex = denied
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--baseline-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    report = run(args.task_id, args.baseline_source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
