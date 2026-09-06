"""Audit descriptive player behavior buckets against stored event edges and rosters.

Read-only historical engineering checks; not independent silver-label validation.
No model calls. Existing output files are never overwritten.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.graph_rag_service import GraphRAGClient


def audit(db_path: Path) -> dict:
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    client = GraphRAGClient(db_path)
    checks = []
    with sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        rounds = {f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}": json.loads(row['properties'])
                  for row in db.execute("SELECT * FROM nodes WHERE node_type='round'")}
        for player in client.players(limit=100):
            profile = client.player_context(player['player_id'])
            selected = set(profile['sample_scope']['participation_round_ids'])
            raw_groups = {key: set() for key in ('opening_kills', 'opening_deaths', 'trade_kills', 'utility', 'flash_blinds', 'plants')}
            for row in db.execute('SELECT n.*,e.relation FROM edges e JOIN nodes n ON n.node_id=e.source_id WHERE e.target_id=?', (profile['graph_id'],)):
                source = f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
                if source not in selected:
                    continue
                props = json.loads(row['properties'])
                key = {('grenade', 'THROWER'): 'utility', ('flash', 'FLASHER'): 'flash_blinds',
                       ('plant', 'PLANTER'): 'plants'}.get((props.get('kind'), row['relation']))
                if props.get('kind') == 'kill' and props.get('is_first_kill'):
                    key = {'KILLER': 'opening_kills', 'VICTIM': 'opening_deaths'}.get(row['relation'])
                if row['relation'] == 'INVOLVES_PLAYER' and props.get('label_type') == 'TRADE_KILL' and props.get('details', {}).get('trader_steamid') == player['player_id']:
                    key = 'trade_kills'
                if key:
                    raw_groups[key].add(source)
            errors = []
            outcomes = {}
            for source in selected:
                props = rounds[source]
                participant = next((p for p in props.get('participants', []) if str(p.get('steamid')) == player['player_id']), None)
                if not props.get('participants_complete') or not participant:
                    errors.append('raw-roster-oracle-unavailable')
                    continue
                winner = props.get('winner')
                outcomes[source] = 'unknown' if winner not in ('T', 'CT') else 'wins' if winner == participant['side'] else 'losses'
            for group in profile['behavior_outcomes']['groups']:
                for name, sources in [('observed', raw_groups[group['key']]), ('not_observed', selected - raw_groups[group['key']])]:
                    bucket = group[name]
                    expected = Counter(outcomes.get(source, 'unknown') for source in sources)
                    decided = expected['wins'] + expected['losses']
                    rate = round(expected['wins'] * 100 / decided, 2) if decided else None
                    if bucket['rounds'] != len(sources) or bucket['decided_rounds'] != decided or bucket['round_win_pct'] != rate or any(bucket[key] != expected[key] for key in ('wins', 'losses', 'unknown')):
                        errors.append(f"{group['key']}:{name}:counts")
                    for sample in bucket['examples']:
                        source = sample['source_id']
                        outcome = {'wins':'won', 'losses':'lost', 'unknown':'unknown'}.get(outcomes.get(source))
                        if source not in sources or sample['outcome'] != outcome or not client.round_detail(source):
                            errors.append(f"{group['key']}:{name}:reference")
            checks.append({'player': player['name'], 'rounds': len(selected), 'passed': not errors, 'errors': sorted(set(errors))})
    scenarios = []
    for name, filters in [('NiKo', {}), ('NiKo', {'map_name':'Nuke', 'side':'CT'}), ('donk', {'opponent':'Spirit'})]:
        profile = client.player_context(name, **filters)
        if profile:
            scenarios.append({'player':name, 'filters':profile['filters'], 'behavior_outcomes':profile['behavior_outcomes']})
    return {'created_at':datetime.now(timezone.utc).isoformat(), 'scope':__doc__.strip(),
            'graph_sha256':before, 'graph_unchanged':before == hashlib.sha256(db_path.read_bytes()).hexdigest(),
            'implementation_sha256':hashlib.sha256(Path('app/services/graph_rag_service.py').read_bytes()).hexdigest(),
            'players':len(checks), 'passed':sum(row['passed'] for row in checks), 'checks':checks, 'scenarios':scenarios}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-db', type=Path, default=Path('data/graph/cs2_graph.sqlite'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new versioned path')
    report = audit(args.graph_db)
    with args.output.open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps({key:report[key] for key in ('players','passed','graph_unchanged')}))
    sys.exit(0 if report['players'] and report['players'] == report['passed'] and report['graph_unchanged'] else 1)
