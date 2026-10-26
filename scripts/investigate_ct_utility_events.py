"""Read-only event ledger; no repaired study data is written."""

from collections import Counter
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.repair_ct_independent_utility import PROJECTILE_CLASS


def ledger(projectiles, weapon_fire):
    f = weapon_fire.copy()
    f['weapon'] = f['weapon'].astype('string').str.removeprefix('weapon_')
    f = f[f['weapon'].isin(PROJECTILE_CLASS)].copy()
    f['user_steamid'] = f['user_steamid'].astype('string')
    f['grenade_type'] = f['weapon'].map(PROJECTILE_CLASS)
    fires = dict(tuple(f.groupby(['user_steamid', 'grenade_type'], sort=False)))
    p = projectiles.sort_values(['grenade_entity_id', 'tick']).copy()
    p['steamid'] = p['steamid'].astype('string')
    p['frame'] = p['tick'].map({t: i for i, t in enumerate(sorted(p['tick'].unique()))})
    g = p.groupby('grenade_entity_id', sort=False)
    same = (g['steamid'].shift() == p['steamid']) & (g['grenade_type'].shift() == p['grenade_type'])
    first = (g['tick'].diff() != 1) | ~same
    previous = g['tick'].shift()
    gaps = ((g['tick'].diff() > 1) & (g['frame'].diff() == 1) & same
            & g[['x', 'y', 'z']].shift().eq(p[['x', 'y', 'z']]).all(axis=1))
    merged = 0
    for i, row in p[gaps.fillna(False)].iterrows():
        group = fires.get((row['steamid'], row['grenade_type']))
        if group is not None and not ((group['tick'] > previous.loc[i]) & (group['tick'] <= row['tick'])).any():
            first.loc[i] = False
            merged += 1
    matched, issues, seen = [], [], set()
    for key, group in p[first.fillna(True)].groupby(['steamid', 'grenade_type'], sort=False):
        seen.add(key)
        rows = fires[key].sort_values('tick').to_dict('records') if key in fires else []
        times, used = [r['tick'] for r in rows], set()
        for birth in group.sort_values('tick').to_dict('records'):
            i = int(np.searchsorted(times, birth['tick'], side='right')) - 1
            item = {'tick': int(birth['tick']), 'user_steamid': key[0], 'grenade_type': key[1],
                    'entity_id': int(birth['grenade_entity_id'])}
            if i < 0 or i in used:
                issues.append({'kind': 'unpaired_projectile_birth', **item})
            else:
                used.add(i)
                matched.append({**item, 'weapon': rows[i]['weapon'], 'fire_tick': int(rows[i]['tick'])})
        issues.extend({'kind': 'unpaired_weapon_fire', 'tick': int(r['tick']), 'user_steamid': key[0],
                       'weapon': r['weapon'], 'grenade_type': key[1]} for i, r in enumerate(rows) if i not in used)
    for key in fires.keys() - seen:
        issues.extend({'kind': 'unpaired_weapon_fire', 'tick': int(r['tick']), 'user_steamid': key[0],
                       'weapon': r['weapon'], 'grenade_type': key[1]} for r in fires[key].to_dict('records'))
    return f, matched, issues, merged


def analyze(mid, source, contexts):
    import psutil
    from demoparser2 import DemoParser

    assert psutil.virtual_memory().available >= 2.5 * 2**30
    started = time.monotonic()
    path = ROOT / source['demo_path']
    native = DemoParser(str(path))
    fired = native.parse_event('weapon_fire', player=['team_name', 'last_place_name'])
    projectiles = native.parse_grenades(grenades=False)
    firing, paired, issues, gaps = ledger(projectiles, fired)
    del projectiles
    deaths = native.parse_event('player_death')
    raw = json.loads((ROOT / f'output/tagnet/ct_independent_inputs/{mid}/snapshots.json').read_text(encoding='utf-8'))
    rounds = [r for r in raw['rounds'] if r['side'] == 'CT']
    sample = next(r for r in sorted(paired, key=lambda r: r['fire_tick']) if r['weapon'] == 'flashbang')
    ticks = {r['tick'] + dt for r in issues for dt in [-1, 0, 1]}
    ticks |= {r['tick'] + dt for r in issues if r['kind'] == 'unpaired_weapon_fire' for dt in range(-1, 11)}
    ticks |= {sample[key] + dt for key in ['fire_tick', 'tick'] for dt in [-1, 0, 1]}
    props = ['health', 'team_name', 'active_weapon_name', 'Grenade.m_bPinPulled',
             'Grenade.m_fThrowTime', 'CCSPlayerController.m_nTickBase', 'game_time']
    attrs = native.parse_ticks(props, ticks=sorted(ticks))
    attrs['steamid'] = attrs['steamid'].astype('string')
    for row in issues:
        at = attrs[(attrs['tick'] == row['tick']) & (attrs['steamid'] == row['user_steamid'])]
        row['native_state_at_tick'] = json.loads(at.to_json(orient='records'))
        trace = attrs[attrs['tick'].isin(range(row['tick'] - 1, row['tick'] + (11 if row['kind'] == 'unpaired_weapon_fire' else 2)))
                      & (attrs['steamid'] == row['user_steamid'])]
        row['native_state_window'] = json.loads(trace.to_json(orient='records'))
        d = deaths[deaths['user_steamid'].astype('string') == row['user_steamid']]
        row['nearby_death_ticks'] = [int(t) for t in d['tick'] if abs(int(t) - row['tick']) <= 64]
        row['query_rounds_containing_issue'] = [r['round_number'] for r in rounds
            if r['freeze_end_tick'] <= row['tick'] <= r['snapshots'][-1]['tick']]
        actual = next((r for r in rounds if r['start_tick'] <= row['tick'] <= r['end_tick']), None)
        if actual:
            row['round'] = actual['round_number']
            row['seconds_since_freeze'] = (row['tick'] - actual['freeze_end_tick']) / 64
        nearest = firing[(firing['user_steamid'] == row['user_steamid']) & (firing['grenade_type'] == row['grenade_type'])]
        row['nearest_same_owner_class_fire_ticks'] = sorted(map(int, nearest['tick']), key=lambda t: abs(t - row['tick']))[:4]
        previous = next((v for v in row['native_state_window'] if v['tick'] == row['tick'] - 1), {})
        now = next((v for v in row['native_state_window'] if v['tick'] == row['tick']), {})
        row['primed_death_drop_pattern'] = bool(row['kind'] == 'unpaired_projectile_birth'
            and row['tick'] in row['nearby_death_ticks'] and previous.get('health', 0) > 0
            and now.get('health') == 0 and previous.get('Grenade.m_bPinPulled') is True
            and previous.get('Grenade.m_fThrowTime') == 0)
    assert all(r['tick'] >= r['fire_tick'] for r in paired)
    direct = native.parse_event('grenade_thrown', player=['team_name'])
    dedicated = isinstance(direct, pd.DataFrame) and len(direct) > 0
    for row in issues:
        row['dedicated_events_same_owner_tick'] = json.loads(direct[(direct['tick'] == row['tick']) &
            (direct['user_steamid'] == row['user_steamid'])].to_json(orient='records')) if dedicated else None
    team = native.parse_ticks(['team_name'], ticks=sorted({r['tick'] for r in paired}))
    team['user_steamid'] = team['steamid'].astype('string')
    releases = pd.DataFrame(paired).merge(team[['tick', 'user_steamid', 'team_name']],
        on=['tick', 'user_steamid'], how='left', validate='many_to_one')
    releases = releases.rename(columns={'team_name': 'user_team_name'})
    assert releases['user_team_name'].notna().all()
    cols = ['tick', 'user_steamid', 'weapon', 'user_team_name']
    full_parity = Counter(map(tuple, releases[cols].to_numpy())) == Counter(map(tuple, direct[cols].to_numpy())) if dedicated else None
    compared = matched_counts = 0
    for row in contexts:
        if not row['id'].startswith(source['sha256'] + ':'):
            continue
        for snapshot in row['snapshots']:
            selected = releases[(releases['tick'] >= row['freeze_end_tick']) & (releases['tick'] <= snapshot['tick'])
                                & (releases['user_team_name'] == 'CT')]
            counts = dict(Counter(selected['weapon']))
            compared += 1
            matched_counts += counts == snapshot['utility']['recorded_ct_throws']
    trace = attrs[(attrs['steamid'] == sample['user_steamid']) & attrs['tick'].isin(
        {sample[key] + dt for key in ['fire_tick', 'tick'] for dt in [-1, 0, 1]})]
    report = {'status': 'diagnostic_only_no_study_inputs_changed', 'match_id': mid,
              'parser_version': importlib.metadata.version('demoparser2'),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'demo_sha256': source['sha256'],
              'utility_firing_events': len(firing), 'paired_releases': len(paired),
              'issue_counts': dict(Counter(r['kind'] for r in issues)), 'issues': issues,
              'stationary_recording_gaps_merged': gaps,
              'paired_release_lag_ticks': dict(Counter(r['tick'] - r['fire_tick'] for r in paired)),
              'sample_paired_flash': {**sample, 'native_state_window': json.loads(trace.to_json(orient='records'))},
              'dedicated_event_available': dedicated, 'full_identity_tick_weapon_side_parity': full_parity,
              'CT_query_counts_compared': compared if dedicated else None,
              'CT_query_counts_matched': matched_counts if dedicated else None,
              'elapsed_seconds': time.monotonic() - started,
              'peak_RAM_MiB': psutil.Process().memory_info().peak_wset / 2**20,
              'limits': ['No recovered context adopted. Death coincidence alone does not prove automatic-drop semantics.',
                         'The event ledger mirrors the existing pairing; entity serial and server action stages require separate evidence.']}
    return report


def main():
    acquisition = json.loads((ROOT / 'output/tagnet/ct_independent_demos/acquisition.json').read_text(encoding='utf-8'))
    repair = json.loads((ROOT / 'datasets/evaluation/ct_independent_context_repair_report.json').read_text(encoding='utf-8'))
    contexts = json.loads((ROOT / 'output/tagnet/ct_independent_context/context.json').read_text(encoding='utf-8'))
    sources = {r['match_id']: r for r in acquisition['files']}
    ids = ['2394200'] + [r['match_id'] for r in repair['demos'] if r['dedicated_event_available']]
    reports = []
    for mid in ids:
        reports.append(analyze(mid, sources[mid], contexts))
        gc.collect()
        row = reports[-1]
        print(json.dumps({'match_id': mid, 'issues': row['issue_counts'],
                          'full_parity': row['full_identity_tick_weapon_side_parity'],
                          'query_parity': [row['CT_query_counts_matched'], row['CT_query_counts_compared']]}), flush=True)
    controls = reports[1:]
    assert len(controls) == 8
    assert all(r['full_identity_tick_weapon_side_parity'] for r in controls)
    assert sum(r['CT_query_counts_compared'] for r in controls) == 830
    assert sum(r['CT_query_counts_matched'] for r in controls) == 830
    report = {'status': 'diagnostic_only_no_study_inputs_changed', 'base_revision': 'c4991c80e5b508f1ea434b89f925db033e4579c0',
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'demos': reports,
              'controls': {'attempted': 8, 'full_event_parity_passed': 8, 'query_counts_matched': 830,
                           'query_counts_compared': 830, 'total_dedicated_releases': sum(r['paired_releases'] for r in controls)}}
    target = ROOT / 'datasets/evaluation/ct_utility_event_investigation.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
