import json
import sqlite3
from pathlib import Path

from app.services.graph_rag_service import GraphRAGClient
from scripts.audit_historical_rebuild import audit


def test_rebuild_audit_accepts_aligned_rosters_and_rejects_dangling_edge(tmp_path):
    filename = 'Alpha_Bravo_1234567_map1.dem'
    paths = [tmp_path/'old.sqlite', tmp_path/'new.sqlite']
    for path, count in zip(paths, [3, 2]):
        roster = [{'steamid':str(i+100),'name':f'p{i}','team':'Alpha' if i<5 else 'Bravo',
                   'side':'T' if i<5 else 'CT'} for i in range(10)]
        parsed = {'map_name':'de_mirage','rounds':[
            {'round_number':i,'winner':'T','participants_complete':True,'participants':roster,
             'roster_tick':i*100+50,'kills':[],'grenades':[],'flash_blinds':[],'plants':[]}
            for i in range(1,count+1)]}
        with sqlite3.connect(path) as db:
            GraphRAGClient._create_schema(db)
            nodes,edges=GraphRAGClient._graph_rows(Path(filename),parsed)
            db.executemany('INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?)',nodes)
            db.executemany('INSERT OR REPLACE INTO edges VALUES (?,?,?,?)',edges)
    boundaries=tmp_path/'boundaries.json'
    boundaries.write_text(json.dumps([{'file':filename,'old_rounds':3,'live_rounds':2,'start_tick':100}]))
    report=audit(*paths,boundaries)
    assert report['passed'] and report['participant_rounds']==20
    with sqlite3.connect(paths[1]) as db:
        db.execute("INSERT INTO edges VALUES ('missing','KILL','also_missing','{}')")
    report=audit(*paths,boundaries)
    assert not report['passed'] and report['dangling_edges']==1
