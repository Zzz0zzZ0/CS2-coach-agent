"""Read-only acceptance of a rebuilt graph against the frozen raw-demo boundary audit."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from app.services.graph_rag_service import GraphRAGClient
from scripts.evaluate_fair_retrieval import digest, write_json


def audit(before, after, boundaries):
    expected = {row['file']: row for row in json.loads(boundaries.read_text())}
    with sqlite3.connect(before.resolve().as_uri()+'?mode=ro', uri=True) as old, \
         sqlite3.connect(after.resolve().as_uri()+'?mode=ro', uri=True) as new:
        def inventory(db):
            return {(m, name): json.loads(props)['source_file'] for m, name, props in db.execute(
                "SELECT match_id,map_name,properties FROM nodes WHERE node_type='map'")}
        maps = inventory(new)
        if maps != inventory(old) or set(maps.values()) != set(expected):
            raise ValueError('Rebuild must preserve the exact frozen map inventory')
        checks, participation = [], Counter()
        for (mid, name), filename in sorted(maps.items()):
            rule = expected[filename]
            rows = new.execute("SELECT round_number,properties FROM nodes WHERE node_type='round' AND match_id=? AND map_name=?", (mid,name)).fetchall()
            old_count = old.execute("SELECT count(*) FROM nodes WHERE node_type='round' AND match_id=? AND map_name=?", (mid,name)).fetchone()[0]
            rosters = [json.loads(p) for _,p in rows]
            events = [json.loads(p) for p, in new.execute("SELECT properties FROM nodes WHERE node_type='event' AND match_id=? AND map_name=?", (mid,name))]
            for number, raw in rows:
                for p in json.loads(raw)['participants']:
                    participation[str(p['steamid'])] += 1
            valid = {
                'frozen_old_count': old_count == rule['old_rounds'],
                'expected_live_count': len(rows) == rule['live_rounds'],
                'sequential_rounds': sorted(int(n) for n,_ in rows) == list(range(1,rule['live_rounds']+1)),
                'complete_rosters': all(p.get('participants_complete') and len({v['steamid'] for v in p['participants']}) == 10 for p in rosters),
                'rosters_after_restart': all(p.get('roster_tick',0) > rule['start_tick'] for p in rosters),
                'events_after_restart': all(p.get('tick',0) > rule['start_tick'] for p in events),
            }
            checks.append({'match_id':mid,'map':name,'file':filename,'old_rounds':old_count,'rounds':len(rows),
                           'event_counts':dict(Counter(p['kind'] for p in events)), 'checks':valid,'passed':all(valid.values())})
        dangling = new.execute('SELECT count(*) FROM edges e LEFT JOIN nodes s ON s.node_id=e.source_id LEFT JOIN nodes t ON t.node_id=e.target_id WHERE s.node_id IS NULL OR t.node_id IS NULL').fetchone()[0]
        event_paths = new.execute("SELECT count(*) FROM nodes e WHERE e.node_type='event' AND (SELECT count(*) FROM edges l JOIN nodes r ON r.node_id=l.source_id WHERE l.target_id=e.node_id AND r.node_type='round' AND r.match_id=e.match_id AND r.map_name=e.map_name AND r.round_number=e.round_number)!=1").fetchone()[0]
        integrity = new.execute('PRAGMA integrity_check').fetchone()[0]
        counts = dict(new.execute('SELECT node_type,count(*) FROM nodes GROUP BY node_type'))
    client = GraphRAGClient(after)
    players = client.players(limit=100)
    player_checks = []
    for p in players:
        context = client.player_context(p['player_id'])
        expected_rounds = participation[p['player_id']]
        passed = (p['sample_size']['rounds'] == context['sample_size']['rounds'] == expected_rounds
                  and context['data_quality']['estimated_rounds'] == 0)
        player_checks.append({'player_id':p['player_id'],'name':p['name'],'rounds':expected_rounds,'passed':passed})
    return {'version':'historical-rebuild-v2','before_sha256':digest(before),'after_sha256':digest(after),
            'boundary_audit_sha256':digest(boundaries),'audit_source_sha256':digest(__file__),
            'counts':counts,'participant_rounds':sum(participation.values()),'maps':checks,'players':player_checks,
            'dangling_edges':dangling,'event_path_errors':event_paths,'integrity':integrity,
            'passed': all(c['passed'] for c in checks+player_checks) and len(players)==len(participation)
                      and dangling==event_paths==0 and integrity=='ok',
            'limitations':['AI-assisted engineering audit; the frozen boundary evidence is not human/video gold.',
                           'Old round IDs in affected maps require the old database snapshot; do not mix benchmark versions.']}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True)
    p.add_argument('--after',type=Path,required=True)
    p.add_argument('--boundaries',type=Path,default=Path('datasets/evaluation/historical_round_boundary_audit_v1.json'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    report=audit(args.before,args.after,args.boundaries)
    write_json(args.output,report)
    print(json.dumps({k:report[k] for k in ('passed','counts','participant_rounds','dangling_edges','event_path_errors')},ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)
