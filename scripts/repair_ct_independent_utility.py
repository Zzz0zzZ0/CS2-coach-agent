"""Recover release ticks from projectile births; weapon_fire alone is earlier."""

from collections import Counter
import gc
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.acquire_ct_independent_demos import digest
from scripts.audit_ct_context_availability import utility_summary
from scripts.confirm_ct_generalization import write
from app.services.ct_context_retrieval_service import context_groups

PROJECTILE_CLASS = {
    'smokegrenade': 'CSmokeGrenadeProjectile', 'flashbang': 'CFlashbangProjectile',
    'hegrenade': 'CHEGrenadeProjectile', 'molotov': 'CMolotovProjectile',
    'incgrenade': 'CMolotovProjectile', 'decoy': 'CDecoyProjectile',
}


def projectile_release_events(projectiles, weapon_fire, intervals=None):
    """Require a complete, causal one-to-one pairing; never shift firing ticks."""
    required = {'grenade_type', 'grenade_entity_id', 'tick', 'steamid', 'x', 'y', 'z'}
    if not isinstance(projectiles, pd.DataFrame) or not required <= set(projectiles):
        raise ValueError('Projectile schema unavailable')
    if not {'tick', 'user_steamid', 'weapon'} <= set(weapon_fire):
        raise ValueError('Weapon-fire schema unavailable')
    p = projectiles.sort_values(['grenade_entity_id', 'tick']).copy()
    if not set(p['grenade_type']) <= set(PROJECTILE_CLASS.values()):
        raise ValueError('Unrecognized projectile class; held grenades are not releases')
    if not np.isfinite(p[['x', 'y', 'z']].to_numpy()).all():
        raise ValueError('Projectile positions unavailable')
    p['steamid'] = p['steamid'].astype('string')
    if not p['steamid'].str.fullmatch(r'[1-9][0-9]*').fillna(False).all():
        raise ValueError('Projectile owner unresolved')
    firing = weapon_fire.copy()
    firing['weapon'] = firing['weapon'].astype('string').str.removeprefix('weapon_')
    firing = firing[firing['weapon'].isin(PROJECTILE_CLASS)].copy()
    firing['user_steamid'] = firing['user_steamid'].astype('string')
    firing['grenade_type'] = firing['weapon'].map(PROJECTILE_CLASS)
    b = dict(tuple(firing.groupby(['user_steamid', 'grenade_type'], sort=False)))
    p['frame'] = p['tick'].map({tick: i for i, tick in enumerate(sorted(p['tick'].unique()))})
    g = p.groupby('grenade_entity_id', sort=False)
    same_owner_class = (g['steamid'].shift() == p['steamid']) & (g['grenade_type'].shift() == p['grenade_type'])
    first = (g['tick'].diff() != 1) | ~same_owner_class
    previous_tick = g['tick'].shift()
    stationary_gap = ((g['tick'].diff() > 1) & (g['frame'].diff() == 1) & same_owner_class
                      & g[['x', 'y', 'z']].shift().eq(p[['x', 'y', 'z']]).all(axis=1))
    merged_gaps = 0
    for i, row in p[stationary_gap.fillna(False)].iterrows():
        fired = b.get((row['steamid'], row['grenade_type']))
        if fired is not None and not ((fired['tick'] > previous_tick.loc[i]) & (fired['tick'] <= row['tick'])).any():
            # A globally unrecorded tick does not create a second stationary projectile.
            first.loc[i] = False
            merged_gaps += 1
    births = p[first.fillna(True)]
    a = dict(tuple(births.groupby(['steamid', 'grenade_type'], sort=False)))
    rows, ignored, unresolved = [], 0, []
    for key, group in a.items():
        born = group.sort_values('tick').to_dict('records')
        fired = b[key].sort_values('tick').to_dict('records') if key in b else []
        ticks = [event['tick'] for event in fired]
        used = set()
        for birth in born:
            i = int(np.searchsorted(ticks, birth['tick'], side='right')) - 1
            if i < 0 or i in used:
                relevant = intervals is None or any(start <= birth['tick'] <= end for start, end in intervals)
                if relevant:
                    if intervals is None:
                        raise ValueError('Unpaired projectile: ambiguous firing order inside query interval')
                    unresolved.append({'tick': int(birth['tick']), 'user_steamid': key[0], 'grenade_type': key[1]})
                    continue
                ignored += 1
                continue
            used.add(i)
            event = fired[i]
            rows.append({'tick': int(birth['tick']), 'user_steamid': key[0], 'weapon': event['weapon'],
                         'fire_tick': int(event['tick'])})
        if len(used) != len(fired):
            raise ValueError('Projectile and firing counts disagree')
    if b.keys() - a.keys():
        raise ValueError('Projectile and firing owners/classes disagree')
    result = pd.DataFrame(rows, columns=['tick', 'user_steamid', 'weapon', 'fire_tick'])
    result.attrs['stationary_recording_gaps_merged'] = merged_gaps
    result.attrs['unpaired_projectiles_outside_queries'] = ignored
    result.attrs['unpaired_projectiles_inside_queries'] = unresolved
    return result


def main():
    import psutil
    from demoparser2 import DemoParser

    protocol = ROOT / 'datasets/selections/ct_independent_utility_repair.json'
    cfg = json.loads(protocol.read_text(encoding='utf-8'))
    for name, expected in cfg['input_sha256'].items():
        assert digest(ROOT / name) == expected, name
    assert importlib.metadata.version('demoparser2') == '0.41.3'
    out = ROOT / 'output/tagnet/ct_independent_context_v2'
    assert not out.exists()
    out.mkdir()
    original = json.loads((ROOT / 'output/tagnet/ct_independent_context/context.json').read_text(encoding='utf-8'))
    records = json.loads(json.dumps(original))
    qa = json.loads((ROOT / 'output/tagnet/ct_independent_inputs/report.json').read_text(encoding='utf-8'))
    acquisition = json.loads((ROOT / 'output/tagnet/ct_independent_demos/acquisition.json').read_text(encoding='utf-8'))
    started = time.monotonic()
    demos, changed, controls, unresolved_windows = [], 0, 0, []
    for receipt in qa['demos']:
        mid = receipt['match_id']
        source = next(r for r in acquisition['files'] if r['match_id'] == mid)
        path = ROOT / source['demo_path']
        assert digest(path) == source['sha256']
        assert psutil.virtual_memory().available >= 2 * 2**30
        native = DemoParser(str(path))
        intervals = [(r['freeze_end_tick'], max(s['tick'] for s in r['snapshots']))
                     for r in records if r['id'].startswith(source['sha256'] + ':')]
        direct = native.parse_event('grenade_thrown', player=['team_name', 'last_place_name'])
        dedicated = isinstance(direct, pd.DataFrame) and len(direct) > 0
        fired = native.parse_event('weapon_fire', player=['team_name', 'last_place_name'])
        trajectories = native.parse_grenades(grenades=False)
        try:
            recovered = projectile_release_events(trajectories, fired, intervals)
        except ValueError as error:
            if not dedicated:
                unresolved_windows.extend({'match_id': mid, 'id': r['id']} for r in records
                                          if r['id'].startswith(source['sha256'] + ':'))
            demos.append({'match_id': mid, 'demo_sha256': source['sha256'], 'dedicated_event_available': dedicated,
                          'derivation_status': 'withheld', 'reason': str(error), 'repaired_snapshots': 0})
            print(json.dumps({'completed_demos': len(demos), 'derivation_withheld': mid, 'reason': str(error)}), flush=True)
            del native, fired, trajectories, direct
            gc.collect()
            continue
        merged_gaps = recovered.attrs['stationary_recording_gaps_merged']
        ignored = recovered.attrs['unpaired_projectiles_outside_queries']
        unresolved = recovered.attrs['unpaired_projectiles_inside_queries']
        del trajectories
        attributes = native.parse_ticks(['team_name', 'last_place_name'],
                                        ticks=sorted(set(recovered['tick']) | {r['tick'] for r in unresolved}))
        attributes['user_steamid'] = attributes['steamid'].astype('string')
        attributes = attributes.rename(columns={'team_name': 'user_team_name', 'last_place_name': 'user_last_place_name'})
        recovered = recovered.merge(attributes[['tick', 'user_steamid', 'user_team_name', 'user_last_place_name']],
                                    on=['tick', 'user_steamid'], how='left', validate='many_to_one')
        assert recovered['user_team_name'].notna().all()
        side_at = attributes.set_index(['tick', 'user_steamid'])['user_team_name'].to_dict()
        uncertain = [r for r in unresolved if side_at.get((r['tick'], r['user_steamid'])) not in ('TERRORIST', 'T')]
        safe_intervals = [(start, end) for start, end in intervals if not any(start <= r['tick'] <= end for r in uncertain)]
        if dedicated:
            keys = ['tick', 'user_steamid', 'weapon', 'user_team_name']
            assert safe_intervals
            relevant = lambda frame: frame[(frame['user_team_name'] == 'CT') & np.logical_or.reduce(
                [(frame['tick'] >= start) & (frame['tick'] <= end) for start, end in safe_intervals])]
            assert Counter(map(tuple, relevant(direct)[keys].to_numpy())) == Counter(map(tuple, relevant(recovered)[keys].to_numpy())), mid
            controls += 1
        checked = modified = 0
        for row in records:
            if not row['id'].startswith(source['sha256'] + ':'):
                continue
            row_unknown = False
            for snapshot in row['snapshots']:
                ambiguous = any(row['freeze_end_tick'] <= r['tick'] <= snapshot['tick'] for r in uncertain)
                utility = utility_summary(recovered, row['freeze_end_tick'], snapshot['tick'])
                if dedicated:
                    if ambiguous:
                        continue
                    for key in ('recorded_ct_throws', 'unattributed_recorded_throws'):
                        assert utility[key] == snapshot['utility'][key], (mid, row['id'], snapshot['second'], key)
                    checked += 1
                else:
                    assert snapshot['utility']['observation_status'] == 'throw_event_unavailable'
                    if ambiguous:
                        snapshot['utility']['observation_status'] = 'unpaired_projectile_release'
                        row_unknown = True
                    else:
                        utility['observation_status'] = 'projectile_release_recovered'
                        snapshot['utility'] = utility
                        modified += 1
            if not dedicated:
                if row_unknown:
                    unresolved_windows.append({'match_id': mid, 'id': row['id']})
                else:
                    changed += 1
        write(out / f'{mid}_release_events.json', json.loads(recovered.to_json(orient='records')))
        demos.append({'match_id': mid, 'demo_sha256': source['sha256'], 'dedicated_event_available': dedicated,
                      'recovered_releases': len(recovered), 'raw_weapon_fire_utility_names': dict(Counter(
                          fired.loc[fired['weapon'].astype('string').str.removeprefix('weapon_').isin(PROJECTILE_CLASS), 'weapon'])),
                      'birth_minus_firing_tick_distribution': dict(Counter(map(int, recovered['tick'] - recovered['fire_tick']))),
                      'control_snapshots_checked': checked, 'repaired_snapshots': modified,
                      'stationary_recording_gaps_merged': merged_gaps,
                      'unpaired_projectiles_outside_queries': ignored,
                      'unpaired_projectiles_inside_queries': len(unresolved), 'uncertain_CT_projectiles_inside_queries': len(uncertain),
                      'safe_query_interval_CT_release_identity_time_side_parity': True if dedicated else None})
        print(json.dumps({'completed_demos': len(demos), 'repaired_windows': changed, 'positive_controls': controls}), flush=True)
        del native, fired, recovered, attributes, direct
        gc.collect()
    attempted_controls = sum(r['dedicated_event_available'] for r in demos)
    assert attempted_controls == 8 and controls > 0 and changed + len(unresolved_windows) == 80
    groups = context_groups(records)
    assert all(not np.isinf(v).any() for v in groups.values())
    for before, after in zip(original, records):
        assert {k: v for k, v in before.items() if k != 'snapshots'} == {k: v for k, v in after.items() if k != 'snapshots'}
        for a, b in zip(before['snapshots'], after['snapshots']):
            assert {k: v for k, v in a.items() if k != 'utility'} == {k: v for k, v in b.items() if k != 'utility'}
    write(out / 'context.json', records)
    report = {'status': 'complete_projectile_release_repair', 'protocol_sha256': digest(protocol),
              'parser_version': importlib.metadata.version('demoparser2'), 'windows': len(records), 'repaired_windows': changed,
              'partially_repaired_windows': unresolved_windows,
              'positive_control_demos': controls, 'demos': demos,
              'positive_control_demos_attempted': attempted_controls,
              'complete_windows_by_group': {k: int(np.isfinite(v).all(1).sum()) for k, v in groups.items()},
              'parent_context_sha256': digest(ROOT / 'output/tagnet/ct_independent_context/context.json'),
              'context_sha256': digest(out / 'context.json'), 'elapsed_seconds': time.monotonic() - started,
              'peak_RAM_MiB': psutil.Process().memory_info().peak_wset / 2**20,
              'limits': ['Dedicated event absence is not absence of all utility information.',
                         'Weapon-fire values have a weapon_ prefix and occur earlier; their ticks are not release ticks.',
                         'Projectile births supply observed release ticks; firing supplies subtype, including incendiary versus molotov.',
                         'All eight dedicated-event Demos are probed; qualified derivations require exact safe-query CT identity/time/side and count parity. Withheld derivations are explicit.',
                         'No new matches, model training, clustering fit or label; old contexts and results remain available.',
                         'Unpaired CT projectiles leave affected snapshot counts unknown; unpaired T projectiles do not alter CT counts.',
                         'Birth segmentation closes only observed stationary recording gaps; other incomplete/ambiguous pairing fails closed.']}
    write(out / 'report.json', report)


if __name__ == '__main__':
    main()
