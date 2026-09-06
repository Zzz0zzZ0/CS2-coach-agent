import sqlite3
from pathlib import Path
import pytest
from app.services.graph_rag_service import GraphRAGClient

@pytest.fixture
def player_graph(tmp_path):
    graph = GraphRAGClient(tmp_path/'graph.sqlite')
    with sqlite3.connect(graph.db_path) as db:
        graph._create_schema(db)
        for match,team,opponent,roster in [('m1','Alpha','Bravo',['111','222']),('m2','Beta','Gamma',['111','222'])]:
            rounds=[]
            for number in (1,2):
                present = '333' if match=='m1' and number==2 else '111'
                rounds.append({'round_number':number,'winner':'T','participants_complete':True,
                    'participants':[{'steamid':present,'name':'entry' if present=='111' else 'sub','team':team,'side':'T'},
                                    {'steamid':'222','name':'defender','team':opponent,'side':'CT'}],
                    'kills':[{'tick':number*100,'killer':'entry' if present=='111' else 'sub','killer_steamid':present,
                        'killer_team':team,'killer_side':'T','victim':'defender','victim_steamid':'222',
                        'victim_team':opponent,'victim_side':'CT','is_first_kill':True,'is_headshot':False}]})
            nodes,edges=graph._graph_rows(Path(match+'.dem'),{'match_id':match,'map_name':'Mirage','rounds':rounds})
            db.executemany('INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?)',nodes)
            db.executemany('INSERT OR REPLACE INTO edges VALUES (?,?,?,?)',edges)
    return graph


def test_substitution_roster_excludes_unplayed_round(player_graph):
    result=player_graph.player_profile('111')
    assert result['sample_size']['rounds']==3
    assert result['data_quality']['confirmed_rounds']==3
    assert result['rates_per_100_rounds']['kills']==100


def test_context_keeps_per_match_team_and_opponent(player_graph):
    result=player_graph.player_context('111')
    assert result['sample_size']['rounds']==3
    assert {row['team'] for row in result['teams']}=={'Alpha','Beta'}
    assert player_graph.player_context('111',opponent='Bravo')['sample_size']['rounds']==1
    assert player_graph.player_context('111',opponent='Gamma')['sample_size']['rounds']==2


def test_no_sample_is_not_zero_performance(player_graph):
    result=player_graph.player_context('111',map_name='Nuke')
    assert result['sample_size']['rounds']==0
    assert result['rates_per_100_rounds']['kills'] is None
    assert result['combat']['headshot_pct'] is None
    assert result['data_quality']['status']=='no_sample'


def test_roster_enrichment_keeps_backup_and_edges(player_graph, tmp_path, monkeypatch):
    from scripts import enrich_player_rosters
    for name in ('m1','m2'):
        (tmp_path/(name+'.dem')).write_bytes(b'fixture')
    class Parser:
        def __init__(self, path): pass
        def parse_round_rosters(self):
            return {i:{'participants':[], 'participants_complete':False,'roster_tick':i*10} for i in (1,2)}
    monkeypatch.setattr(enrich_player_rosters, 'TacticalDemoParser', Parser)
    result=enrich_player_rosters.enrich(player_graph.db_path,tmp_path,True)
    assert result['applied'] and Path(result['backup']).exists()
    with sqlite3.connect(player_graph.db_path) as current, sqlite3.connect(result['backup']) as previous:
        assert current.execute('SELECT COUNT(*) FROM edges').fetchone()==previous.execute('SELECT COUNT(*) FROM edges').fetchone()
        assert current.execute("SELECT SUM(json_extract(properties,'$.participants_complete')) FROM nodes WHERE node_type='round'").fetchone()[0]==0
        assert previous.execute("SELECT SUM(json_extract(properties,'$.participants_complete')) FROM nodes WHERE node_type='round'").fetchone()[0]==4


def test_roster_alignment_failure_does_not_write(player_graph, tmp_path, monkeypatch):
    from scripts import enrich_player_rosters
    for name in ('m1','m2'):
        (tmp_path/(name+'.dem')).write_bytes(b'fixture')
    class Parser:
        def __init__(self, path): pass
        def parse_round_rosters(self): return {}
    monkeypatch.setattr(enrich_player_rosters, 'TacticalDemoParser', Parser)
    before=player_graph.db_path.read_bytes()
    with pytest.raises(ValueError,match='alignment'):
        enrich_player_rosters.enrich(player_graph.db_path,tmp_path,True)
    assert player_graph.db_path.read_bytes()==before


def test_empty_player_search_does_not_generate_a_coaching_brief(player_graph):
    import asyncio
    query='entry 在 Nuke 的首杀'
    evidence=asyncio.run(player_graph.retrieve(query,global_search=True))
    assert not evidence
    assert player_graph.player_brief(query,evidence) is None
