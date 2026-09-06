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


def test_behavior_outcomes_use_player_team_and_exclude_unknown_results(player_graph):
    with sqlite3.connect(player_graph.db_path) as db:
        db.execute("UPDATE nodes SET properties=json_set(properties, '$.winner', 'CT') WHERE node_type='round' AND match_id='m2' AND round_number=1")
        db.execute("UPDATE nodes SET properties=json_set(properties, '$.winner', NULL) WHERE node_type='round' AND match_id='m2' AND round_number=2")
    entry = player_graph.player_context('111')['behavior_outcomes']
    assert {k: entry['baseline'][k] for k in ('rounds', 'wins', 'losses', 'unknown', 'decided_rounds', 'round_win_pct')} == {
        'rounds': 3, 'wins': 1, 'losses': 1, 'unknown': 1, 'decided_rounds': 2, 'round_win_pct': 50,
    }
    opening = entry['groups'][0]
    assert opening['observed']['rounds'] == 3
    assert opening['not_observed']['round_win_pct'] is None
    assert opening['win_rate_difference_pp'] is None
    assert {x['outcome'] for x in opening['observed']['examples']} == {'won', 'lost', 'unknown'}
    assert {x['team'] for x in opening['observed']['examples']} == {'Alpha', 'Beta'}
    defender = player_graph.player_context('222')['behavior_outcomes']
    assert [defender['baseline'][key] for key in ('wins', 'losses', 'unknown')] == [1, 2, 1]
    assert defender['groups'][1]['observed']['rounds'] == 4
    assert player_graph.player_context('111', opponent='Bravo')['behavior_outcomes']['baseline']['rounds'] == 1


def test_behavior_deduplicates_events_and_uses_disjoint_complement(player_graph):
    import json
    with sqlite3.connect(player_graph.db_path) as db:
        for kind, relation in [('grenade', 'THROWER'), ('flash', 'FLASHER'), ('plant', 'PLANTER')]:
            for index in (1, 2):
                node_id = f'test:{kind}:{index}'
                db.execute('INSERT INTO nodes (node_id,node_type,match_id,map_name,round_number,label,properties) VALUES (?,?,?,?,?,?,?)',
                           (node_id, 'event', 'm1', 'Mirage', 1, kind, json.dumps({'kind':kind})))
                db.execute('INSERT INTO edges (source_id,target_id,relation,properties) VALUES (?,?,?,?)',
                           (node_id, 'player:111', relation, '{}'))
    profile = player_graph.player_context('111')
    assert profile['utility']['thrown'] == 2
    for group in profile['behavior_outcomes']['groups'][3:]:
        assert group['observed']['rounds'] == 1
        assert group['not_observed']['rounds'] == 2
        assert group['win_rate_difference_pp'] == 0
        observed = {row['source_id'] for row in group['observed']['examples']}
        other = {row['source_id'] for row in group['not_observed']['examples']}
        assert observed == {'graph:m1:Mirage:1'}
        assert not observed & other
        assert all(player_graph.round_detail(source) for source in observed | other)


def test_behavior_empty_and_unknown_only_scopes_never_report_zero_win_rate(player_graph):
    empty = player_graph.player_context('111', side='CT')['behavior_outcomes']
    assert empty['baseline']['rounds'] == 0
    assert empty['baseline']['round_win_pct'] is None
    assert all(group['observed']['round_win_pct'] is None and group['not_observed']['round_win_pct'] is None
               for group in empty['groups'])
    with sqlite3.connect(player_graph.db_path) as db:
        db.execute("UPDATE nodes SET properties=json_set(properties, '$.winner', NULL) WHERE node_type='round'")
    unknown = player_graph.player_context('111')['behavior_outcomes']
    assert unknown['baseline']['unknown'] == 3
    assert unknown['baseline']['decided_rounds'] == 0
    assert unknown['baseline']['round_win_pct'] is None


def test_behavior_counts_are_not_limited_by_evidence_examples(tmp_path):
    graph = GraphRAGClient(tmp_path / 'many-rounds.sqlite')
    rounds = [{'round_number':i, 'winner':'T' if i <= 13 else 'CT', 'participants_complete':True,
               'participants':[{'steamid':'111','name':'entry','team':'Alpha','side':'T'},
                               {'steamid':'222','name':'defender','team':'Bravo','side':'CT'}],
               'kills':[{'tick':i*100,'killer':'entry','killer_steamid':'111','killer_team':'Alpha','killer_side':'T',
                         'victim':'defender','victim_steamid':'222','victim_team':'Bravo','victim_side':'CT','is_first_kill':True}]}
              for i in range(1, 16)]
    with sqlite3.connect(graph.db_path) as db:
        graph._create_schema(db)
        nodes, edges = graph._graph_rows(Path('m.dem'), {'match_id':'m','map_name':'Mirage','rounds':rounds})
        db.executemany('INSERT INTO nodes VALUES (?,?,?,?,?,?,?)', nodes)
        db.executemany('INSERT INTO edges VALUES (?,?,?,?)', edges)
    profile = graph.player_context('111')
    opening = profile['behavior_outcomes']['groups'][0]['observed']
    assert opening['rounds'] == 15
    assert opening['round_win_pct'] == 86.67
    assert len(profile['source_round_ids']) == 12
    assert len(opening['examples']) == 5  # three wins and both losses, not just early winning rounds
    assert {x['outcome'] for x in opening['examples']} == {'won', 'lost'}


def test_trade_outcomes_count_only_the_trader_and_deduplicate_labels(player_graph):
    import json
    with sqlite3.connect(player_graph.db_path) as db:
        for index, trader, traded in [(1, '111', '333'), (2, '111', '333'), (3, '333', '111')]:
            node_id = f'test:trade:{index}'
            props = {'label_type':'TRADE_KILL', 'details':{'trader_steamid':trader, 'traded_player_steamid':traded}}
            db.execute('INSERT INTO nodes (node_id,node_type,match_id,map_name,round_number,label,properties) VALUES (?,?,?,?,?,?,?)',
                       (node_id, 'tactical_sequence', 'm1', 'Mirage', 1, 'TRADE_KILL', json.dumps(props)))
            db.execute('INSERT INTO edges (source_id,target_id,relation,properties) VALUES (?,?,?,?)',
                       (node_id, 'player:111', 'INVOLVES_PLAYER', '{}'))
    result = player_graph.player_context('111')
    assert result['combat']['trade_kills'] == 2
    assert result['combat']['traded_deaths'] == 1
    trade = next(group for group in result['behavior_outcomes']['groups'] if group['key'] == 'trade_kills')
    assert trade['observed']['rounds'] == 1
    assert trade['not_observed']['rounds'] == 2


@pytest.mark.parametrize('query,metric', [
    ('entry 的首杀', 'opening_kills'), ('entry first death', 'opening_deaths'),
    ('entry 的补枪', 'trade_kills'), ('entry utility', 'utility'),
    ('entry 的闪光', 'flash_blinds'), ('entry plant', 'plants'),
])
def test_grounded_brief_stays_on_requested_behavior(player_graph, query, metric):
    brief = player_graph.player_brief(query, player_graph._player_query_evidence(query, None))
    assert [claim['metric'] for claim in brief['claims']] == [metric]
    assert brief['sample_confidence'] == '未进行统计推断'
    assert brief['sample_scopes'][0]['match_ids'] == ['m1', 'm2']
    sources = {source['id']: source for source in brief['sources']}
    claim = brief['claims'][0]
    assert claim['observed']['rounds'] == (3 if metric == 'opening_kills' else 0)
    assert all(f'[{citation}]' in brief['findings'][1] for citation in claim['citation_ids'])
    for ref in claim['evidence_refs']:
        assert ref['cohort'] == ('observed' if metric == 'opening_kills' else 'not_observed')
        assert sources[ref['citation_id']]['player_id'] == '111'
    if metric != 'opening_kills':
        assert '先检查筛选范围和事件记录' in brief['actions'][0]
        assert '不可计算' in claim['text']


def test_profile_and_query_share_grounded_summary(player_graph):
    profile = player_graph.player_context('111', map_name='Mirage', side='T')
    query = 'entry 在 Mirage T侧的表现'
    brief = player_graph.player_brief(query, player_graph._player_query_evidence(query, None))
    assert brief == profile['brief']
    assert 'K/D 不可计算（3 杀 / 0 死）' in brief['findings'][0]
    assert brief['sample_scopes'][0]['combat'] == profile['combat']
    assert {claim['metric'] for claim in brief['claims']} == {'opening_kills', 'opening_deaths', 'trade_kills'}
    assert player_graph.player_context('111', side='CT')['brief'] is None


def test_brief_unknown_results_and_legacy_samples_are_visible(player_graph):
    with sqlite3.connect(player_graph.db_path) as db:
        db.execute("UPDATE nodes SET properties=json_set(properties, '$.winner', NULL, '$.participants_complete', json('false')) WHERE node_type='round'")
    brief = player_graph.player_context('111')['brief']
    assert brief['sample_scopes'][0]['data_quality']['estimated_rounds'] > 0
    assert '回合估算' in brief['findings'][0]
    assert all(claim['observed']['round_win_pct'] is None and claim['not_observed']['round_win_pct'] is None for claim in brief['claims'])
    assert '名单确认不代表行为标签已人工审核' in brief['caveat']
    assert '比赛日期尚未收录' in brief['caveat']
    assert all(source['outcome'] == 'unknown' for source in brief['sources'])


def test_comparison_citations_keep_player_identity_on_shared_round(player_graph):
    query = '比较 entry 和 defender 的首杀'
    brief = player_graph.player_brief(query, player_graph._player_query_evidence(query, None))
    sources = {row['id']:row for row in brief['sources']}
    assert len(sources) == len(brief['sources'])
    assert len(brief['sample_scopes']) == 2
    assert any('没有共同' in finding for finding in brief['findings'])
    for claim in brief['claims']:
        assert all(sources[ref['citation_id']]['player_id'] == claim['player_id'] for ref in claim['evidence_refs'])
    shared = [row for row in brief['sources'] if row['round_id'] == 'graph:m1:Mirage:1']
    assert {row['player_id'] for row in shared} == {'111', '222'}
    assert {row['outcome'] for row in shared} == {'won', 'lost'}


def test_summary_evaluator_rejects_wrong_values_and_missing_or_wrong_cohort_references(player_graph):
    from copy import deepcopy
    from scripts.evaluate_player_queries import check_grounded_claims
    profile = player_graph.player_context('111')
    original = profile['brief']
    assert check_grounded_claims(original, [profile]) == (True, True)
    changed = deepcopy(original)
    changed['claims'][0]['observed']['wins'] += 1
    assert check_grounded_claims(changed, [profile])[0] is False
    changed = deepcopy(original)
    changed['claims'][0]['evidence_refs'][0]['cohort'] = 'not_observed'
    assert check_grounded_claims(changed, [profile])[1] is False
    changed = deepcopy(original)
    changed['claims'][0]['citation_ids'] = []
    changed['claims'][0]['evidence_refs'] = []
    assert check_grounded_claims(changed, [profile])[1] is False
