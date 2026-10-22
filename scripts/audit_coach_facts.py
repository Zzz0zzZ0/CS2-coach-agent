"""Audit the existing Coach packet and replay its facts locally, without human scores or LLM calls."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3

from app.agentic.nodes.coach_node import _render_report
from app.services.metrics_service import calculate_metrics, build_current_match_evidence
from app.services.parser_service import TacticalDemoParser
from scripts.evaluate_fair_retrieval import digest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    def denied(*args, **kwargs):
        raise RuntimeError('Network forbidden during Coach fact audit')
    socket.socket.connect = socket.socket.connect_ex = denied
    selection = json.loads(Path('datasets/selections/unseen_small_v3.json').read_text())
    baseline_path = args.baseline_root / 'app/services/metrics_service.py'
    graph = Path('data/graph/cs2_graph.sqlite')
    if digest(baseline_path) != selection['implementation_sha256']['app/services/metrics_service.py'] or digest(graph) != selection['historical_graph_sha256']:
        raise ValueError('Frozen baseline or graph hash differs')
    module_spec = importlib.util.spec_from_file_location('frozen_metrics', baseline_path)
    baseline = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(baseline)
    groups = defaultdict(dict)
    with sqlite3.connect(graph.resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        for mid, map_name, n, raw in db.execute("SELECT match_id,map_name,round_number,properties FROM nodes WHERE node_type='round'"):
            n = int(n)
            groups[mid, map_name][n] = {**json.loads(raw), 'round_number': n, 'kills': [], 'grenades': [], 'plants': [], 'flash_blinds': []}
        for mid, map_name, n, raw in db.execute("SELECT match_id,map_name,round_number,properties FROM nodes WHERE node_type='event' ORDER BY json_extract(properties,'$.tick'),node_id"):
            n = int(n)
            event = json.loads(raw)
            field = {'kill':'kills', 'grenade':'grenades', 'plant':'plants', 'flash':'flash_blinds'}.get(event.get('kind'))
            if field:
                groups[mid, map_name][n][field].append(event)
    rounds_by_map = {key:[rows[n] for n in sorted(rows)] for key, rows in groups.items()}
    regression = []
    for (mid, map_name), rounds in sorted(rounds_by_map.items()):
        old, new = baseline.calculate_metrics(rounds), calculate_metrics(rounds)
        changes = [key for key in old if key != 'available_metrics' and old[key] != new[key]]
        coverage = sum(v['rounds'] for sides in new['side_performance_by_team'].values() for v in sides.values()) // 2
        regression.append({'match_id':mid, 'map':map_name, 'rounds':len(rounds), 'existing_metric_changes':changes, 'side_roster_rounds':coverage})
    # Reparse the two previously seen pilot maps; never use new-series data here.
    demo_hashes = {}
    for path in sorted(Path('data/evaluation/unseen_v1/demos').glob('*.dem')):
        if '2396950' not in path.name:
            raise ValueError('Unexpected prior pilot file')
        print(f'Parsing prior pilot {path.name}', flush=True)
        parsed = TacticalDemoParser(str(path)).parse_to_dict()
        map_name = {'dust2':'Dust2', 'mirage':'Mirage'}[parsed['map_name'].removeprefix('de_').lower()]
        key = ('2396950', map_name)
        if key in rounds_by_map:
            raise ValueError('Duplicate prior pilot map')
        rounds_by_map[key] = parsed['rounds']
        demo_hashes[path.name] = digest(path)
    packet_path = Path('data/evaluation/coach_blind_v1_run/review/packet.json')
    packet = json.loads(packet_path.read_text())
    labels = {'首杀后续':'opening_followup', '下包后处理':'post_plant', '道具复核':'utility_review', '攻守转换':'side_transition'}
    cases = []
    for case in packet:
        rounds = rounds_by_map[case['match_id'], case['map_name']]
        metrics = calculate_metrics(rounds)
        changes = [key for key in case['metrics'] if key != 'available_metrics' and case['metrics'][key] != metrics[key]]
        self_events = [{'round':r['round_number'], 'tick':e.get('tick'), 'player':e.get('attacker'), 'team':e.get('attacker_team')}
                       for r in rounds for e in r.get('flash_blinds', []) if e.get('attacker_steamid')
                       and str(e['attacker_steamid']) == str(e.get('victim_steamid'))]
        priorities = {variant:[labels[line.split('**')[1]] for line in text.splitlines() if line[:1].isdigit() and '**' in line]
                      for variant, text in case['candidates'].items()}
        corrected = {'case_id':case['case_id'], 'metrics':metrics,
                     'current_evidence':build_current_match_evidence(case, metrics),
                     'candidates':{variant:_render_report(metrics, ids) for variant, ids in priorities.items()}}
        artifact = args.output_dir / (case['case_id']+'.json')
        write_json(artifact, corrected)
        cases.append({'case_id':case['case_id'], 'match_id':case['match_id'], 'map':case['map_name'],
                      'existing_metric_changes':changes, 'side_performance_by_team':metrics['side_performance_by_team'],
                      'self_blind_events':len(self_events), 'self_blind_witnesses':self_events[:2],
                      'variants_with_low_win_count_advice':[v for v,t in case['candidates'].items() if '优先检查低胜局一侧' in t],
                      'corrected_render_sha256':digest(artifact)})
    unchanged = digest(graph) == selection['historical_graph_sha256']
    passed = (len(cases) == 6 and unchanged and not any(c['existing_metric_changes'] for c in cases + regression)
              and all(r['rounds'] == r['side_roster_rounds'] for r in regression))
    report = {'status':'ai_assisted_fact_audit', 'passed':passed, 'created_at':datetime.now(timezone.utc).isoformat(),
              'reviewer_kind':'ai_assisted', 'independent_human_review':False, 'model_quality_gain':None, 'new_model_calls':0,
              'packet_sha256':digest(packet_path), 'baseline_commit':'6e3826e', 'history_graph_sha256':digest(graph),
              'implementation_sha256':{p:digest(p) for p in ('scripts/audit_coach_facts.py', 'app/services/metrics_service.py', 'app/agentic/nodes/coach_node.py')},
              'prior_demo_sha256':demo_hashes, 'history_regression':regression, 'cases':cases,
              'limitations':['Developer AI audit; no method key opened, but not an independent blinded reviewer.',
                             'Same parsed facts; fixes concern denominators and wording, not independent video truth.',
                             'Original candidate choices retained; corrected renders are not new model outputs or human scores.']}
    write_json(args.output_dir/'report.json', report)
    print(json.dumps({'passed':passed, 'cases':len(cases), 'history_maps':len(regression)}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
