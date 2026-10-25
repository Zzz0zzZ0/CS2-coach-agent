"""Recover the same time-bounded CT-only facets for the frozen new-series windows."""

from collections import Counter
import gc
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acquire_ct_independent_demos import digest
from scripts.confirm_ct_generalization import write
from scripts.audit_ct_context_availability import utility_summary, score_before
from app.services.team_identity_service import canonical_team
from app.services.ct_context_retrieval_service import context_groups, WEAPONS


def main():
    import psutil
    from app.services.parser_service import TacticalDemoParser

    protocol=ROOT/'datasets/selections/ct_independent_context_transfer.json'
    cfg=json.loads(protocol.read_text(encoding='utf-8'))
    for name,expected in cfg['input_sha256'].items():assert digest(ROOT/name)==expected,name
    qa=json.loads((ROOT/'output/tagnet/ct_independent_inputs/report.json').read_text(encoding='utf-8'))
    assert qa['status']=='complete_inputs_pending_inference' and not qa['unresolved_team_identities']
    acquisition=json.loads((ROOT/'output/tagnet/ct_independent_demos/acquisition.json').read_text(encoding='utf-8'))
    old_context=json.loads((ROOT/'output/tagnet/ct_context_availability_v2/context.json').read_text(encoding='utf-8'))
    old_by_id={r['id']:r for r in old_context}
    inventory=json.loads((ROOT/'datasets/evaluation/ct_map_semantics_v8_report.json').read_text(encoding='utf-8'))
    legacy_checks=0
    for relative in inventory['dataset_sha256']:
        if not relative.endswith('_snapshots.json'):continue
        document=json.loads((ROOT/relative).read_text(encoding='utf-8'))
        for row in document['rounds']:
            identity=f"{document['source_demo_sha256']}:{row['round_number']}:CT"
            if row['side']!='CT' or identity not in old_by_id:continue
            for snapshot,context in zip(row['snapshots'],old_by_id[identity]['snapshots']):
                assert snapshot['tick']==context['tick']
                np.testing.assert_allclose(sum(p['equipment_value'] for p in snapshot['players']),
                                           context['equipment_total']['CT'],atol=0,rtol=0)
                legacy_checks+=1
    assert legacy_checks==2325
    out=ROOT/'output/tagnet/ct_independent_context';assert not out.exists();out.mkdir()
    started=time.monotonic();records=[];demos=[];master=[]
    for receipt in qa['demos']:
        mid=receipt['match_id'];folder=ROOT/'output/tagnet/ct_independent_inputs'/mid
        source=next(r for r in acquisition['files'] if r['match_id']==mid)
        path=ROOT/source['demo_path'];assert digest(path)==source['sha256']
        assert digest(folder/'snapshots.json')==receipt['output_sha256']['snapshots.json']
        document=json.loads((folder/'snapshots.json').read_text(encoding='utf-8'))
        index=json.loads((folder/'sample_index.json').read_text(encoding='utf-8'));master.extend(index)
        wanted={r['round_number'] for r in index}
        assert psutil.virtual_memory().available>2*2**30
        loaded=TacticalDemoParser(str(path));native=loaded.parser
        ends,boundary=loaded._completed_rounds()
        raw={r['round_number']:r for r in document['rounds'] if r['side']=='CT'}
        assert len(raw)==len(ends)
        freezes=native.parse_event('round_freeze_end',player=['team_name','team_clan_name'])
        throws=native.parse_event('grenade_thrown',player=['team_name','last_place_name'])
        throws_available=isinstance(throws,pd.DataFrame) and {'tick','user_team_name','user_last_place_name','weapon'}<=set(throws.columns)
        event_list=native.list_game_events()
        history=[];teams_by_round={};previous=boundary
        for number,end in enumerate(ends.to_dict('records'),1):
            row=raw[number];assert row['end_tick']==int(end['tick'])
            choices=freezes[(freezes['tick']>previous)&(freezes['tick']<=end['tick'])]
            freeze=choices.sort_values('tick').iloc[0] if len(choices) else None
            teams={side:canonical_team(freeze[f'{side.lower()}_team_clan_name'])
                   if freeze is not None and pd.notna(freeze[f'{side.lower()}_team_clan_name']) else '' for side in ('CT','T')}
            teams_by_round[number]=teams
            if number in wanted:
                assert freeze is not None and int(freeze['tick'])==row['freeze_end_tick']
                assert canonical_team(row['team'])==teams['CT']
            history.append({'round_number':number,'end_tick':int(end['tick']),'winner_team':teams.get(end['winner'])})
            previous=int(end['tick'])
        for number in sorted(wanted):
            row=raw[number]
            item={'id':f"{source['sha256']}:{number}:CT",'map':source['map'],'freeze_end_tick':row['freeze_end_tick'],
                  'score_before':score_before(history,number,row['start_tick'],teams_by_round[number]),'snapshots':[]}
            for snapshot in row['snapshots']:
                item['snapshots'].append({'second':snapshot['second'],'tick':snapshot['tick'],
                    'equipment_total':{'CT':sum(p['equipment_value'] for p in snapshot['players'])},
                    'utility':utility_summary(throws,row['freeze_end_tick'],snapshot['tick']) if throws_available else {
                        'recorded_ct_throws':{weapon:None for weapon in WEAPONS},
                        'unattributed_recorded_throws':None,'observation_status':'throw_event_unavailable'}})
            records.append(item)
        demos.append({'match_id':mid,'map':source['map'],'selected_windows':len(wanted),
                      'grenade_thrown_event_listed':'grenade_thrown' in event_list,
                      'throws_available':throws_available,
                      'grenade_event_weapons':dict(Counter(throws['weapon'])) if throws_available else None})
        print(json.dumps({'context_demos':len(demos),'context_windows':len(records)}),flush=True)
        del loaded,native,freezes,throws;gc.collect()
    assert [r['id'] for r in records]==[r['id'] for r in master] and len(records)==246
    groups=context_groups(records);assert all(not np.isinf(v).any() for v in groups.values())
    write(out/'context.json',records);write(out/'sample_index.json',master)
    report={'status':'complete_existing_definition_CT_context_facets','protocol_sha256':digest(protocol),
        'windows':len(records),'snapshots':sum(len(r['snapshots']) for r in records),'legacy_equipment_parity_checks':legacy_checks,
        'group_shapes':{k:list(v.shape) for k,v in groups.items()},'demos':demos,
        'complete_windows_by_group':{k:int(np.isfinite(v).all(1).sum()) for k,v in groups.items()},
        'context_sha256':digest(out/'context.json'),'sample_index_sha256':digest(out/'sample_index.json'),
        'elapsed_seconds':time.monotonic()-started,'peak_RAM_MiB':psutil.Process().memory_info().peak_wset/2**20,
        'limits':['Recorded own-CT equipment and throws plus pre-round public score only; no opponent equipment or future outcome input.',
                  'Throw counts are not active areas, visibility, intent, or tactical duty. No new training or labels.']}
    write(out/'report.json',report)


if __name__=='__main__':main()
