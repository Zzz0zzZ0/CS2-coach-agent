"""Export time-audited frozen-version CT inputs, without evaluating a model."""

from collections import Counter
import gc
import importlib.metadata
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.acquire_ct_independent_demos import digest, resolved_primary
from scripts.confirm_ct_generalization import write
from app.services.ct_deployment_service import DEPLOYMENT_VERSION, deployment_sequence
from app.services.opening_timing_service import CLOCK_PROPERTIES, audit_opening_timing
from app.services.team_identity_service import canonical_team


def main():
    import psutil
    from app.services.parser_service import TacticalDemoParser

    protocol_path = ROOT / 'datasets/selections/ct_independent_confirmation.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    for name, expected in protocol['inputs_sha256'].items():
        assert digest(ROOT / name) == expected, f'Frozen input changed: {name}'
    manifest_path = ROOT / 'output/tagnet/ct_independent_demos/acquisition.json'
    acquisition = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert acquisition['protocol_sha256'] == digest(protocol_path)
    cohort = json.loads((ROOT / protocol['cohort_path']).read_text(encoding='utf-8'))
    selected_rows = resolved_primary(cohort, acquisition.get('replacements', {}))
    wanted = {r['match_id']:r['selected_map'] for r in selected_rows}
    assert len(acquisition['files']) <= 12
    old_index = json.loads((ROOT / 'output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json').read_text(encoding='utf-8'))
    old_hashes = {r['id'].split(':')[0] for r in old_index}
    assert len({r['sha256'] for r in acquisition['files']}) == len(acquisition['files'])
    out = ROOT / 'output/tagnet/ct_independent_inputs';out.mkdir(exist_ok=True)
    source_paths = ['app/services/parser_service.py','app/services/opening_snapshot_service.py',
                    'app/services/opening_timing_service.py','app/services/ct_feature_service.py',
                    'app/services/ct_geometry_service.py','app/services/ct_deployment_service.py',
                    'app/services/team_identity_service.py',
                    'scripts/acquire_ct_independent_demos.py',
                    'scripts/export_ct_independent_inputs.py']
    sources = {name:digest(ROOT / name) for name in source_paths}
    receipts = []
    for source in acquisition['files']:
        assert source['map'] == wanted[source['match_id']] and source['sha256'] not in old_hashes
        folder = out / source['match_id'];report_path = folder / 'report.json'
        if report_path.exists():
            receipt = json.loads(report_path.read_text(encoding='utf-8'))
            assert receipt['source_sha256'] == sources and receipt['demo_sha256'] == source['sha256']
            for name, expected in receipt['output_sha256'].items():
                assert digest(folder / name) == expected
            receipts.append(receipt);continue
        assert not folder.exists(), 'Refusing to overwrite a partial export'
        assert psutil.virtual_memory().available > 2 * 2**30, 'RAM guard before native parse'
        path = ROOT / source['demo_path'];assert digest(path) == source['sha256']
        loaded = TacticalDemoParser(str(path));observed = loaded.parse_opening_snapshots()
        assert observed['map_name'] == source['map'], 'Archive member header/map mismatch'
        observed.update(source_demo=path.name,source_demo_sha256=source['sha256'])
        rows = [r for r in observed['rounds'] if r['side'] == 'CT']
        native_teams = sorted({canonical_team(r['team']) for r in observed['rounds'] if r.get('team')})
        selected = next(r for r in selected_rows if r['match_id']==source['match_id'])
        expected_teams = sorted({canonical_team(t) for t in selected['teams']})
        ticks = sorted({r['freeze_end_tick'] + second * 64 for r in rows if r['status']=='ok' for second in range(21)})
        assert ticks, 'No eligible snapshot clock samples; do not request all native ticks'
        clocks = loaded.parser.parse_ticks(CLOCK_PROPERTIES, ticks=ticks)
        timing = audit_opening_timing(observed['rounds'], clocks)
        passed = {r['round_number'] for r in timing['rounds'] if r['passed']}
        candidates = [r for r in rows if r['status']=='ok' and r['round_number'] in passed]
        selected_ticks = sorted({f['tick'] for r in candidates for f in r['snapshots']})
        assert selected_ticks, 'No time-audited snapshots; stop before native feature parsing'
        native = loaded.parser.parse_ticks(['X','Y','Z','health','current_equip_value','is_airborne'], ticks=selected_ticks)
        by_player = {(int(r['tick']), str(r['steamid'])):r for r in native.to_dict('records')}
        assert len(by_player) == len(native), 'Duplicate tick/player observations'
        arrays, index, skipped = [], [], []
        for row in rows:
            if row['status'] != 'ok' or row['round_number'] not in passed:
                skipped.append({'round':row['round_number'],'reason':row.get('reason') or 'engine_timing_failed'});continue
            frames = row['snapshots'];ids = [str(p['steamid']) for p in frames[0]['players']]
            assert len(ids)==len(set(ids))==5 and all([str(p['steamid']) for p in f['players']]==ids for f in frames)
            if not all(any(p['alive'] for p in f['players']) for f in frames):
                skipped.append({'round':row['round_number'],'reason':'no_live_CT_at_a_supplied_time'});continue
            context = []
            for frame in frames:
                for player in frame['players']:
                    native_row = by_player[(frame['tick'],str(player['steamid']))]
                    np.testing.assert_allclose([native_row[k] for k in ('X','Y','Z','health','current_equip_value')],
                                              [*player['position'],player['health'],player['equipment_value']],atol=1e-5,rtol=0)
                    air = native_row['is_airborne']
                    context.append({'second':frame['second'],'steamid':player['steamid'],'position':player['position'],
                                    'is_airborne':bool(air) if isinstance(air,(bool,np.bool_)) else None})
            features = deployment_sequence(frames,context)
            assert features['nodes'].shape==(5,5,15) and features['edges'].shape==(5,5,5,3)
            assert np.isfinite(features['nodes']).all() and np.isfinite(features['edges']).all()
            arrays.append(features);index.append({'id':f"{source['sha256']}:{row['round_number']}:CT",
                'series':source['match_id'],'map':source['map'],'round_number':row['round_number']})
        assert arrays, 'No eligible CT inputs; resolve the cohort before any inference'
        folder.mkdir()
        write(folder/'snapshots.json',observed);write(folder/'timing.json',timing);write(folder/'sample_index.json',index)
        np.savez_compressed(folder/'features.npz',**{key:np.stack([r[key] for r in arrays])
            for key in ('nodes','edges','node_mask','node_feature_mask','pair_mask')})
        receipt = {'match_id':source['match_id'],'map':source['map'],'demo_sha256':source['sha256'],
            'feature_version':DEPLOYMENT_VERSION,'windows':len(index),'CT_rounds':len(rows),'skipped':skipped,
            'native_teams':native_teams,'expected_teams':expected_teams,'teams_match':native_teams==expected_teams,
            'parser_version':importlib.metadata.version('demoparser2'),'source_sha256':sources,
            'output_sha256':{p.name:digest(p) for p in folder.iterdir()},'new_model_outputs':False}
        write(report_path,receipt);receipts.append(receipt)
        print(json.dumps({'exported_demos':len(receipts),'match_id':source['match_id'],'windows':len(index),
                          'available_RAM_GiB':round(psutil.virtual_memory().available/2**30,2)}),flush=True)
        del loaded,native,clocks,by_player,arrays;gc.collect()
    complete = len(receipts)==12 and {r['match_id'] for r in receipts}==set(wanted)
    report = {'status':'complete_inputs_pending_inference' if complete else 'partial_inputs_pending_remaining_acquisition',
        'protocol_sha256':digest(protocol_path),'acquisition_manifest_sha256':digest(manifest_path),
        'demos':receipts,'windows':sum(r['windows'] for r in receipts),'maps':dict(Counter(r['map'] for r in receipts)),
        'source_sha256':sources,'peak_RAM_MiB':psutil.Process().memory_info().peak_wset/2**20,
        'context_facets_exported':False,'new_model_outputs':False,'NAV_required':False}
    report['unresolved_team_identities'] = [r['match_id'] for r in receipts if not r['teams_match']]
    write(out/'report.json',report)


if __name__ == '__main__':
    main()
