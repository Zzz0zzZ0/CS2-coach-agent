"""Bounded natural-language relation search over read-only parsed events.

No model calls or benchmark labels. Unsupported qualifiers must not become
optional ranking terms. Evidence is filtered over the scope before top-k.
"""
import json
from pathlib import Path
import re
import sqlite3

HANDLE = r'[a-z0-9_$-]{1,32}'
MAPS = {name.lower():name for name in ('Ancient','Anubis','Cache','Dust2','Inferno','Mirage','Nuke','Overpass','Vertigo')}
MESSAGES = {
    'found':'已找到满足关系条件的源事件。',
    'not_found':'已核查限定范围，未找到满足关系条件的回合。',
    'unknown':'现有数据或范围不足，无法确认该关系是否存在。',
    'unsupported':'暂不支持完整解析这个关系问题，请明确主体、对手、比赛或地图及 tick 条件。',
}


def relation_intent(query):
    text=query.casefold()
    directed=re.search(rf'({HANDLE})\s+(?:(?:did|does|not|never)\s+)*kill(?:s|ed|ing)?\s+({HANDLE})',text)
    if directed and directed[1] not in {'opening','first','trade','total'} and directed[2] not in {'on','in','per','by'}:
        return True
    if re.search(rf'{HANDLE}\s*(?:被\s*{HANDLE}\s*)?(?:(?:没有|并未|未|不)\s*)?首杀\s*{HANDLE}|{HANDLE}\s*被\s*{HANDLE}\s*(?:击杀|首杀)|{HANDLE}\s+(?:was|is)\s+(?:not\s+)?(?:first\s+)?(?:killed|traded)\s+by\s+{HANDLE}|{HANDLE}\s+avenged\s+{HANDLE}',text):
        return True
    return bool(re.search(rf'{HANDLE}\s+(?:was|is)\s+killed\s+by\s+{HANDLE}|{HANDLE}\s+(?:makes|gets|got|wins)\s+(?:the\s+)?(?:opening first|opening|first)\s+kill.*(?:killing|against)\s+{HANDLE}|{HANDLE}\s*(?:没有|并未|未|不)?击杀\s*{HANDLE}|{HANDLE}\s*为\s*(?:队友)?\s*{HANDLE}.*补枪|{HANDLE}\s+trad(?:es|ed)\s+(?:teammate\s+)?{HANDLE}',text))


def parse_relation(query, metadata=None):
    if not relation_intent(query): return None
    result={'status':'unsupported','reason':'unsupported_syntax','query':query}
    text=query.casefold().strip().rstrip('.。?!？！')
    scope={}
    # Remove only explicit scope clauses; full-match the remaining relation.
    for field,pattern in [('match_id',rf'(?:\bmatch|比赛)\s+({HANDLE})'),
                          ('map',rf'(?:\bmap|地图)\s+({HANDLE})')]:
        values=re.findall(pattern,text)
        if len(set(values))>1: return {**result,'reason':'conflicting_scope'}
        if values:
            scope[field]=values[0]
            text=re.sub(pattern,'',text)
    text=text.strip(' ,，.。;；')
    text=re.sub(r'^(?:(?:find|show)\s+rounds\s+where\s+|查找\s*)','',text)
    for key,value in (metadata or {}).items():
        if value is None: continue
        if key not in ('map','match_id','round','round_number'):
            return {**result,'reason':'unsupported_scope_filter'}
        field='round' if key=='round_number' else key
        normalized=str(value).casefold().removeprefix('de_') if field=='map' else str(value).casefold()
        existing=scope.get(field)
        if field=='map' and existing is not None: existing=existing.removeprefix('de_')
        if existing is not None and existing != normalized: return {**result,'reason':'conflicting_scope'}
        scope[field]=normalized
    if 'map' in scope:
        raw=scope['map'].removeprefix('de_'); scope['map']=MAPS.get(raw,raw)
    if 'round' in scope:
        if not scope['round'].isdigit() or int(scope['round'])<1: return {**result,'reason':'invalid_round'}
        scope['round']=int(scope['round'])
    mode='rounds'
    for name,prefix in [('count',r'^(?:(?:count|how many) rounds where\s+|统计回合数[：:]\s*)'),
                        ('win_rate',r'^(?:round win rate when\s+|回合胜率[：:]\s*)')]:
        text,n=re.subn(prefix,'',text)
        if n: mode=name; break
    a=rf'(?P<actor>{HANDLE})'; b=rf'(?P<target>{HANDLE})'
    patterns={
        'opening':[
            rf'{b}\s+(?:was|is)\s+first killed by\s+{a}',
            rf'{a}\s*首杀\s*{b}',
            rf'{b}\s*被\s*{a}\s*首杀',
            rf'{a}\s+(?:makes|gets|got|wins)\s+(?:the\s+)?(?:opening first|opening|first)\s+kill\s+(?:by\s+)?(?:killing|against)\s+{b}',
            rf'{a}\s*击杀\s*{b}\s*(?:并|且)(?:拿到|取得)(?:本回合)?首杀(?:的回合)?',
        ],
        'after_plant':[
            rf'{b}\s+(?:was|is)\s+killed by\s+{a}\s+after (?:the |a )?bomb (?:plant|was planted)',
            rf'{b}\s*被\s*{a}\s*击杀[，,]?\s*发生在下包之后',
            rf'下包后\s*{a}\s*击杀\s*{b}',
            rf'{a}\s+kill(?:s|ed)\s+{b}\s+(?:strictly\s+)?after\s+(?:a |the )?bomb (?:plant|was planted)(?: in (?:that|the same) round)?',
            rf'{a}\s*击杀\s*{b}\s*[，,]?\s*(?:且这次击杀)?(?:严格)?发生在(?:该回合)?(?:炸弹安放|下包)之后(?:的回合)?',
        ],
        'trade':[
            rf'{b}\s+(?:was|is)\s+traded by\s+{a}\s+within\s+(?P<window>\d+)\s+ticks',
            rf'{a}\s+trad(?:es|ed)\s+(?:teammate\s+)?{b}\s+within\s+(?P<window>\d+)\s+ticks(?: in the same round)?',
            rf'{a}\s+trad(?:es|ed)\s+(?:teammate\s+)?{b}:\s*kills the enemy who killed (?P=target), more than 0 and at most (?P<window>\d+) ticks later in the same round',
            rf'{a}\s*为(?:队友)?\s*{b}\s*补枪[，,：:]?\s*在\s*(?P<window>\d+)\s*ticks?\s*内',
            rf'{a}\s*为(?:队友)?\s*{b}\s*补枪的回合：\s*在同一回合中，\s*(?P=target)\s*被敌人击杀后，\s*(?P=actor)\s*在大于\s*0\s*且不超过\s*(?P<window>\d+)\s*ticks?\s*内击杀该敌人',
        ],
    }
    for family,options in patterns.items():
        for pattern in options:
            match=re.fullmatch(pattern,text)
            if not match: continue
            data=match.groupdict(); window=int(data['window']) if 'window' in data else None
            if data['actor']==data['target']: return {**result,'reason':'distinct_players_required'}
            if window is not None and not 0 < window <= 6400: return {**result,'reason':'invalid_tick_window'}
            if not (scope.get('map') or scope.get('match_id')): return {**result,'reason':'explicit_scope_required'}
            return {'status':'parsed','family':family,'actor':data['actor'],'target':data['target'],
                    'window_ticks':window,'scope':scope,'query':query,'mode':mode}
    return result


def event_witnesses(events, rule):
    """Return proofs and completeness. Missing facts cannot prove absence."""
    kills=[e for e in events if e.get('kind')=='kill']; plants=[e for e in events if e.get('kind')=='plant']
    complete=True
    for event in kills:
        needed=['killer_steamid','victim_steamid','tick']
        if rule['family']=='trade': needed += ['killer_team','victim_team']
        if any(event.get(k) in (None,'','Unknown','None') for k in needed) or type(event.get('tick')) is not int:
            complete=False
        if rule['family']=='opening' and type(event.get('is_first_kill')) is not bool: complete=False
    if rule['family']=='after_plant' and any(type(e.get('tick')) is not int for e in plants): complete=False
    proofs=[]
    for event in kills:
        if type(event.get('tick')) is not int: continue
        if rule['family'] in ('opening','after_plant'):
            if str(event.get('killer_steamid'))!=rule['actor_id'] or str(event.get('victim_steamid'))!=rule['target_id']: continue
            if rule['family']=='opening':
                if event.get('is_first_kill') is True: proofs.append([event])
            else:
                for plant in plants:
                    if type(plant.get('tick')) is int and plant['tick'] < event['tick']: proofs.append([plant,event])
        else:
            if str(event.get('victim_steamid'))!=rule['target_id'] or not event.get('killer_steamid'): continue
            for response in kills:
                team=response.get('killer_team'); other=event.get('killer_team')
                if (type(response.get('tick')) is int and str(response.get('killer_steamid'))==rule['actor_id']
                    and str(response.get('victim_steamid'))==str(event['killer_steamid'])
                    and len({rule['actor_id'],rule['target_id'],str(event['killer_steamid'])})==3
                    and team not in (None,'','Unknown','None') and other not in (None,'','Unknown','None')
                    and team==event.get('victim_team') and team!=other
                    and 0 < response['tick']-event['tick'] <= rule['window_ticks']):
                    proofs.append([event,response])
    return proofs,complete


def search_relations(db_path, query, metadata=None, k=5):
    from app.services.rag_service import Evidence, RetrievalResult
    rule=parse_relation(query,metadata)
    if rule is None: return None
    if type(k) is not int or not 1 <= k <= 100: raise ValueError('k must be between 1 and 100')
    result=RetrievalResult(query=query,rewritten_query=query,filters=rule.get('scope',{}),strategy='graph_relation_exact')
    matched_sources=[]; outcomes={'won':[], 'lost':[], 'unknown':[]}
    state={**rule,'checked_rounds':0,'matched_rounds':0,'unknown_rounds':0,'complete':False}
    result.relation=state
    if rule['status']!='parsed':
        result.warnings=[MESSAGES['unsupported']]; return result
    state['status']='unknown'
    path=Path(db_path)
    if not path.is_file():
        state['reason']='graph_unavailable'; result.warnings=[MESSAGES['unknown']]; return result
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row; db.execute('BEGIN')
            scope=rule['scope']; rounds=db.execute("""SELECT * FROM nodes WHERE node_type='round'
                AND (? IS NULL OR match_id=?) AND (? IS NULL OR map_name=?)
                AND (? IS NULL OR round_number=?) ORDER BY match_id,map_name,CAST(round_number AS INTEGER) LIMIT 5001""",
                (scope.get('match_id'),scope.get('match_id'),scope.get('map'),scope.get('map'),scope.get('round'),scope.get('round'))).fetchall()
            if not rounds or len(rounds)>5000:
                state['reason']='empty_scope' if not rounds else 'scope_limit_exceeded'
            else:
                identities={name:set() for name in (rule['actor'],rule['target'])}
                for row in rounds:
                    for p in json.loads(row['properties']).get('participants',[]):
                        name=str(p.get('name','')).casefold()
                        if name in identities and p.get('steamid') not in (None,'','Unknown','None'): identities[name].add(str(p['steamid']))
                if any(len(values)!=1 for values in identities.values()) or len(set.union(*identities.values())) != 2:
                    state['reason']='unknown_or_ambiguous_player'
                else:
                    rule={**rule,'actor_id':next(iter(identities[rule['actor']])),'target_id':next(iter(identities[rule['target']]))}
                    state.update(actor_id=rule['actor_id'],target_id=rule['target_id'])
                    for row in rounds:
                        props=json.loads(row['properties']); roster=props.get('participants',[])
                        if not props.get('participants_complete'):
                            state['unknown_rounds']+=1; continue
                        ids={str(p.get('steamid')) for p in roster}
                        if not {rule['actor_id'],rule['target_id']} <= ids: continue
                        state['checked_rounds']+=1
                        raw=db.execute("""SELECT node_id,properties FROM nodes WHERE node_type='event'
                            AND match_id=? AND map_name=? AND round_number=? ORDER BY node_id""",
                            (row['match_id'],row['map_name'],row['round_number'])).fetchall()
                        events=[{**json.loads(e['properties']),'event_id':e['node_id']} for e in raw]
                        proofs,complete=event_witnesses(events,rule)
                        if not complete: state['unknown_rounds']+=1
                        if not proofs: continue
                        state['matched_rounds']+=1
                        source=f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
                        matched_sources.append(source)
                        from app.services.graph_rag_service import _side_name
                        sides={_side_name(p.get('side')) for p in roster if str(p.get('steamid'))==rule['actor_id']}
                        winner=_side_name(props.get('winner'))
                        side=next(iter(sides)) if len(sides)==1 else None
                        outcome=('won' if side==winner else 'lost') if side and winner else 'unknown'
                        outcomes[outcome].append(source)
                        if len(result.evidence)>=k: continue
                        # ponytail: exhaustive scan capped at 5000 rounds; add indexed event joins if scope grows.
                        witnesses={e['event_id']:e for proof in proofs for e in proof}
                        sources=list(witnesses)
                        source=f"graph:{row['match_id']}:{row['map_name']}:{row['round_number']}"
                        lines=[f"[Verified relation] {rule['family']} {rule['actor']} -> {rule['target']}. {source}"]
                        for event in witnesses.values():
                            action=(f"{event.get('killer')} killed {event.get('victim')}" if event['kind']=='kill'
                                    else f"{event.get('planter')} planted the bomb")
                            lines.append(f"{event['event_id']} tick {event['tick']}: {action}.")
                        result.evidence.append(Evidence(content='\n'.join(lines),score=1.0,source_id=source,metadata={
                            'context_level':'verified_relation','topic':rule['family'],'tactic_type':'Verified Relation Evidence',
                            'map':row['map_name'],'match_id':row['match_id'],'round_number':row['round_number'],
                            'relation':rule['family'],'actor_id':rule['actor_id'],'target_id':rule['target_id'],
                            'window_ticks':rule['window_ticks'],'witness_event_ids':sources,
                            'witnesses':[[{'event_id':e['event_id'],'tick':e['tick']} for e in proof] for proof in proofs]}))
                    state['complete']=state['unknown_rounds']==0 and state['checked_rounds']>0
                    state['status']='found' if result.evidence else 'not_found' if state['complete'] else 'unknown'
                    state['reason']='verified_source_events' if state['complete'] else 'incomplete_source_scope'
    except (sqlite3.Error,ValueError,TypeError,KeyError):
        # A partial failed scan must not be reported as exhaustive or complete.
        result.evidence=[]; matched_sources=[]; outcomes={'won':[], 'lost':[], 'unknown':[]}
        state.update(status='unknown',reason='source_read_failed',complete=False,matched_rounds=0)
    if rule.get('mode','rounds') != 'rounds':
        known=len(outcomes['won'])+len(outcomes['lost'])
        state['aggregation']={
            'mode':rule['mode'],'observed_matched_rounds':len(matched_sources),
            'exact_matched_rounds':len(matched_sources) if state['complete'] else None,
            'co_present_rounds':state['checked_rounds'],
            'match_rate':len(matched_sources)/state['checked_rounds'] if state['complete'] else None,
            'matched_source_ids':matched_sources,'outcome_source_ids':outcomes,
            'known_outcome_rounds':known,'won_rounds':len(outcomes['won']),
            'unknown_outcome_rounds':len(outcomes['unknown']),
            'observed_win_rate':len(outcomes['won'])/known if known else None,
            'outcome_complete':state['complete'] and not outcomes['unknown'],
        }
    result.confidence=1.0 if result.evidence else 0.0
    if state['status']!='found' or not state['complete']:
        result.warnings=[MESSAGES['unknown' if not state['complete'] and state['status']=='found' else state['status']]]
    return result


def relation_message(state):
    """One numeric contract for API, UI and agent context; evidence is only a sample."""
    message=MESSAGES.get(state['status'],MESSAGES['unknown'])
    stats=state.get('aggregation')
    if not stats: return message
    count=stats['exact_matched_rounds']
    message += f" 匹配回合数：{count}。" if count is not None else f" 已证实至少 {stats['observed_matched_rounds']} 个匹配回合；完整计数未知。"
    if stats['mode']=='win_rate':
        rate=stats['observed_win_rate']
        message += (f" {state['actor']} 在结果已知的 {stats['known_outcome_rounds']} 个匹配回合中获胜 {stats['won_rounds']} 次，观测胜率 {rate:.1%}。"
                    if rate is not None else ' 没有结果已知的匹配回合，胜率未知。')
        if not stats['outcome_complete']: message += ' 范围或结果不完整；该胜率仅描述已知样本。'
    return message+' 下方事件仅为证据样本，统计使用完整扫描。'
