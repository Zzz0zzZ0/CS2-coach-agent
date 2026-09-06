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


def test_comparison_distinguishes_shared_rounds_from_shared_conditions(player_graph):
    result = player_graph.compare_players(['111', '222'])
    sample = result['sample_comparison']
    assert sample['shared_match_ids'] == ['m1', 'm2']
    assert sample['shared_participation_rounds'] == 3  # the substitute's round is excluded
    assert sample['shared_condition_count'] == 0  # opposite sides and opponents
    assert [row['pct'] for row in sample['common_condition_coverage']] == [0, 0]
    assert any('没有共同' in warning for warning in sample['warnings'])
    left = result['players'][0]['sample_scope']
    assert left['composition'] == [
        {'map': 'Mirage', 'side': 'T', 'opponents': ['Bravo'], 'rounds': 1},
        {'map': 'Mirage', 'side': 'T', 'opponents': ['Gamma'], 'rounds': 2},
    ]
    assert len(left['participation_round_ids']) == 3


def test_comparison_common_support_is_not_equal_composition(player_graph):
    result = player_graph.compare_players(['111', '333'])
    sample = result['sample_comparison']
    assert sample['shared_participation_rounds'] == 0  # substitute and starter never coexist
    assert sample['shared_condition_count'] == 1
    assert [row['pct'] for row in sample['common_condition_coverage']] == [33.33, 100]
    assert any('占比不同' in warning for warning in sample['warnings'])
    filtered = player_graph.compare_players(['111', '333'], opponent='Bravo')['sample_comparison']
    assert [row['pct'] for row in filtered['common_condition_coverage']] == [100, 100]
    assert not any('占比不同' in warning for warning in filtered['warnings'])


def test_comparison_empty_scope_and_legacy_denominators_are_explicit(player_graph):
    empty = player_graph.compare_players(['111', '222'], side='T')
    assert empty['sample_comparison']['status'] == 'no_sample'
    assert empty['sample_comparison']['common_condition_coverage'][1]['pct'] is None
    assert empty['players'][1]['combat']['kd_ratio'] is None
    with sqlite3.connect(player_graph.db_path) as db:
        db.execute("UPDATE nodes SET properties=json_set(properties, '$.participants_complete', json('false')) WHERE node_type='round'")
    legacy = player_graph.compare_players(['111', '222'])
    assert any('旧数据估算' in warning for warning in legacy['sample_comparison']['warnings'])


@pytest.mark.parametrize('qualifier', ['对阵 Bravo', 'against Bravo', 'vs Bravo'])
def test_natural_comparison_applies_opponent_to_both_players(player_graph, monkeypatch, qualifier):
    # The fixture has no tactical sequences; expose its teams to the existing NL team resolver.
    monkeypatch.setattr('app.services.graph_rag_service.TEAM_ALIASES', {'bravo': 'bravo'})
    query = f'比较 entry 和 sub 在 Mirage T侧 {qualifier} 的首杀'
    evidence = player_graph._player_query_evidence(query, None)
    assert len(evidence) == 1
    metadata = evidence[0].metadata
    direct = player_graph.compare_players(['111', '333'], map_name='Mirage', side='T', opponent='Bravo')
    assert metadata['profiles'] == direct['players']
    assert metadata['sample_comparison'] == direct['sample_comparison']
    assert metadata['opponent'] == 'Bravo'
    brief = player_graph.player_brief(query, evidence)
    assert brief['sample_confidence'] == '未进行统计推断'
    assert '筛选一致不代表样本组成一致' in brief['summary']
    assert not player_graph._player_query_evidence(f'比较 entry 和 defender {qualifier}', None)


def test_comparison_team_mentions_are_not_implicit_opponents(player_graph, monkeypatch):
    monkeypatch.setattr('app.services.graph_rag_service.TEAM_ALIASES', {'alpha': 'alpha', 'bravo': 'bravo'})
    evidence = player_graph._player_query_evidence('Compare Alpha entry and Bravo defender', None)
    assert evidence[0].metadata['opponent'] is None
    assert [p['sample_size']['rounds'] for p in evidence[0].metadata['profiles']] == [3, 4]


def test_unknown_comparison_opponent_never_broadens_to_all_matches(player_graph):
    assert not player_graph._player_query_evidence('比较 entry 和 sub 对阵 NonexistentTeam', None)
    assert player_graph._player_query_evidence('Compare entry vs sub', None)
