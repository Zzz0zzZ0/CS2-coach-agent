"""Add freeze-end rosters to an existing graph, without rebuilding events or vectors."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.parser_service import TacticalDemoParser


def enrich(graph_db: Path, demo_dir: Path, apply: bool = False) -> dict:
    connection = sqlite3.connect(f'file:{graph_db}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        maps = connection.execute("SELECT match_id,map_name,properties FROM nodes WHERE node_type='map'").fetchall()
        updates, players = [], {}
        for row in maps:
            path = demo_dir / json.loads(row['properties'])['source_file']
            if not path.is_file():
                raise FileNotFoundError(path)
            rosters = TacticalDemoParser(str(path)).parse_round_rosters()
            rounds = connection.execute("SELECT node_id,round_number,properties FROM nodes WHERE node_type='round' AND match_id=? AND map_name=?",
                (row['match_id'],row['map_name'])).fetchall()
            if {int(r['round_number']) for r in rounds} != set(rosters):
                raise ValueError(f'Round alignment mismatch: {path.name}')
            for item in rounds:
                roster = rosters[int(item['round_number'])]
                props = {**json.loads(item['properties']), **roster}
                updates.append((json.dumps(props, ensure_ascii=False),item['node_id']))
                for player in roster['participants']:
                    pid = 'player:' + player['steamid']
                    players[pid] = (pid,'player',player['name'],None,None,None,
                        json.dumps({'name':player['name'],'steamid':player['steamid']}))
        report = {'maps':len(maps),'rounds':len(updates),
            'complete_rosters':sum(json.loads(props)['participants_complete'] for props,_ in updates),
            'applied':apply,'backup':None}
        if apply:
            backup = graph_db.with_name(graph_db.stem + '.before-rosters-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite')
            with sqlite3.connect(backup) as destination:
                connection.backup(destination)
            with sqlite3.connect(graph_db) as target:
                target.executemany('UPDATE nodes SET properties=? WHERE node_id=?',updates)
                target.executemany('INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?)',players.values())
            report['backup'] = str(backup)
        return report
    finally:
        connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-db',type=Path,default=Path('data/graph/cs2_graph.sqlite'))
    parser.add_argument('--demo-dir',type=Path,default=Path('data/demos'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=enrich(args.graph_db,args.demo_dir,args.apply)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text+'\n')
    print(text)

if __name__=='__main__':
    main()
