from copy import deepcopy

import pytest

from scripts.benchmark_relations import relation_text, source_index, sql_witnesses, witnesses


def kill(eid, tick, killer, victim, team='A', victim_team='B', first=False):
    return {'id':eid,'kind':'kill','properties':{'tick':tick,'killer_steamid':killer,
        'victim_steamid':victim,'killer_team':team,'victim_team':victim_team,
        'killer':killer,'victim':victim,'killer_side':'CT','victim_side':'TERRORIST',
        'is_first_kill':first,'weapon':'ak47'}}


def check(events, rule, expected, relaxed=False):
    doc={'id':'round:fixture','events':events}; query={'relation':rule}
    db=source_index([doc])
    try:
        assert witnesses(doc,query,relaxed)==expected
        assert sql_witnesses(db,doc['id'],query,relaxed)==expected
    finally: db.close()


@pytest.mark.parametrize('delay,expected', [(-1,[]),(0,[]),(1,[['death','response']]),
    (320,[['death','response']]),(321,[])])
def test_trade_window_excludes_reverse_and_tie_but_includes_exact_boundary(delay,expected):
    death=kill('death',1000,'enemy','teammate','B','A')
    response=kill('response',1000+delay,'trader','enemy')
    rule={'family':'trade','actor':'trader','target':'teammate','window_ticks':320}
    check([response,death],rule,expected)  # Input order must not stand in for event time.


@pytest.mark.parametrize('field,value', [('killer_steamid','other'),('victim_steamid','other'),
    ('killer_team','B'),('killer_team','C')])
def test_trade_requires_named_trader_same_enemy_and_teammate_team(field,value):
    response=kill('response',1100,'trader','enemy'); response['properties'][field]=value
    check([kill('death',1000,'enemy','teammate','B','A'),response],
          {'family':'trade','actor':'trader','target':'teammate','window_ticks':320},[])


def test_late_response_is_only_a_near_miss_and_self_trade_is_invalid():
    events=[kill('death',1000,'enemy','teammate','B','A'),kill('response',1500,'trader','enemy')]
    rule={'family':'trade','actor':'trader','target':'teammate','window_ticks':320}
    check(events,rule,[['death','response']],True)
    rule['actor']='teammate'; events[1]['properties']['killer_steamid']='teammate'
    check(events,rule,[],True)


@pytest.mark.parametrize('tick,expected',[(99,[]),(100,[]),(101,[['plant','kill']])])
def test_after_plant_strict_time_and_named_kill(tick,expected):
    plant={'id':'plant','kind':'plant','properties':{'tick':100}}
    rule={'family':'after_plant','actor':'a','target':'b'}
    events=[kill('kill',tick,'a','b'),plant]
    check(events,rule,expected)
    events[0]['properties']['killer_steamid']='someone_else'
    check(events,rule,[])


def test_opening_subject_is_not_merely_a_round_participant():
    rule={'family':'opening','actor':'a','target':'b'}
    check([kill('other',1,'b','a',first=True),kill('later',2,'a','b')],rule,[])
    check([kill('first',1,'a','b',first=True)],rule,[['first']])


def test_text_representation_contains_observable_time_and_roles_without_labels():
    doc={'text':'Match fixture.\nParticipant a team A side CT.\nOld aggregate.',
         'events':[kill('later',321,'a','b'),kill('early',1,'b','a','B','A',True)]}
    original=deepcopy(doc); text=relation_text(doc)
    assert 'Tick 1:' in text and 'Tick 321:' in text
    assert text.index('Tick 1:') < text.index('Tick 321:')
    assert 'a team A side CT kills b team B' in text
    assert 'trade' not in text and 'after plant' not in text
    assert 'Old aggregate.' not in text
    assert doc==original
