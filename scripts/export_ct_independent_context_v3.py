"""Conservative utility recovery: retain unvalidated HE death-drop snapshots as unknown."""

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
from scripts.investigate_ct_utility_events import ledger
from app.services.ct_context_retrieval_service import WEAPONS, context_groups


def interrupted_before_release(issue):
    states = issue['native_state_window']
    fire = next(r for r in states if r['tick'] == issue['tick'])
    deadline = fire.get('Grenade.m_fThrowTime')
    return bool(deadline and fire.get('Grenade.m_bPinPulled') is False
                and deadline > fire['game_time'] and any(
                    r['tick'] in issue['nearby_death_ticks'] and r['health'] == 0
                    and fire['game_time'] < r['game_time'] < deadline for r in states))


def uncertain_CT_births(issues, validated_classes):
    uncertain = []
    for issue in issues:
        if issue['kind'] != 'unpaired_projectile_birth':
            continue
        state = issue['native_state_at_tick']
        side = state[0]['team_name'] if len(state) == 1 else None
        if side in ('TERRORIST', 'T'):
            continue
        if issue['primed_death_drop_pattern'] and issue['grenade_type'] in validated_classes:
            continue
        uncertain.append(issue['tick'])
    return sorted(uncertain)


def self_check():
    birth = {'kind': 'unpaired_projectile_birth', 'tick': 123, 'primed_death_drop_pattern': True,
             'grenade_type': 'CHEGrenadeProjectile', 'native_state_at_tick': [{'team_name': 'CT'}]}
    assert uncertain_CT_births([birth], {'CSmokeGrenadeProjectile'}) == [123]
    assert uncertain_CT_births([{**birth, 'grenade_type': 'CSmokeGrenadeProjectile'}], {'CSmokeGrenadeProjectile'}) == []
    assert uncertain_CT_births([{**birth, 'native_state_at_tick': [{'team_name': 'TERRORIST'}]}], set()) == []
    event = {'tick': 10, 'nearby_death_ticks': [11], 'native_state_window': [
        {'tick': 10, 'health': 3, 'Grenade.m_bPinPulled': False, 'Grenade.m_fThrowTime': 5.1, 'game_time': 5.0},
        {'tick': 11, 'health': 0, 'game_time': 5.05}]}
    assert interrupted_before_release(event)
    event['native_state_window'][1]['game_time'] = 5.15
    assert not interrupted_before_release(event)


def main():
    import psutil
    from demoparser2 import DemoParser

    self_check()
    protocol = ROOT / 'datasets/selections/ct_independent_context_v3.json'
    cfg = json.loads(protocol.read_text(encoding='utf-8'))
    for name, expected in cfg['input_sha256'].items():
        assert digest(ROOT / name) == expected, name
    assert importlib.metadata.version('demoparser2') == '0.41.3'
    out = ROOT / 'output/tagnet/ct_independent_context_v3'
    assert not out.exists()
    started = time.monotonic()
    def guard(minimum=1.5):
        free = psutil.virtual_memory().available / 2**30
        if free < minimum:
            raise RuntimeError(f'Available RAM {free:.3f} GiB below required {minimum:.1f} GiB; no v3 output written')
    guard(2)
    evidence = json.loads((ROOT / 'datasets/evaluation/ct_utility_event_investigation.json').read_text(encoding='utf-8'))
    assert evidence['controls'] == {'attempted': 8, 'full_event_parity_passed': 8, 'query_counts_matched': 830,
                                   'query_counts_compared': 830, 'total_dedicated_releases': 3553}
    controls = evidence['demos'][1:]
    assert len(controls) == 8 and all(r['full_identity_tick_weapon_side_parity'] for r in controls)
    counterexamples = [issue for r in controls for issue in r['issues']
                       if issue['kind'] == 'unpaired_projectile_birth']
    assert len(counterexamples) == 2 and all(r['primed_death_drop_pattern']
        and r['dedicated_events_same_owner_tick'] == [] for r in counterexamples)
    validated = {r['grenade_type'] for r in counterexamples}
    assert validated == {'CSmokeGrenadeProjectile'}
    target = next(r for r in evidence['demos'] if r['match_id'] == '2394200')
    issues = target['issues']
    uncertain = uncertain_CT_births(issues, validated)
    assert uncertain == [183539]
    for issue in issues:
        if issue['kind'] == 'unpaired_weapon_fire':
            assert interrupted_before_release(issue) and not issue['query_rounds_containing_issue']
    before = json.loads((ROOT / 'output/tagnet/ct_independent_context_v2/context.json').read_text(encoding='utf-8'))
    records = json.loads(json.dumps(before))
    path = ROOT / 'output/tagnet/ct_independent_demos/2394200__de_inferno.dem'
    assert digest(path) == target['demo_sha256']
    guard(2)
    native = DemoParser(str(path))
    firing = native.parse_event('weapon_fire', player=['team_name', 'last_place_name'])
    guard()
    projectiles = native.parse_grenades(grenades=False)
    guard()
    _, paired, actual_issues, gaps = ledger(projectiles, firing)
    assert len(paired) == target['paired_releases'] == 482
    signature = lambda rows: sorted((r['kind'], r['tick'], r['user_steamid'], r['grenade_type']) for r in rows)
    assert signature(actual_issues) == signature(issues)
    del projectiles, firing
    gc.collect()
    guard()
    attributes = native.parse_ticks(['team_name', 'last_place_name'], ticks=sorted({r['tick'] for r in paired}))
    attributes['user_steamid'] = attributes['steamid'].astype('string')
    releases = pd.DataFrame(paired).merge(attributes[['tick', 'user_steamid', 'team_name', 'last_place_name']],
                                        on=['tick', 'user_steamid'], how='left', validate='many_to_one')
    releases = releases.rename(columns={'team_name': 'user_team_name', 'last_place_name': 'user_last_place_name'})
    assert releases['user_team_name'].notna().all()
    changed, unresolved = [], []
    for row in records:
        if not row['id'].startswith(target['demo_sha256'] + ':'):
            continue
        for snapshot in row['snapshots']:
            if any(row['freeze_end_tick'] <= t <= snapshot['tick'] for t in uncertain):
                snapshot['utility'] = {'recorded_ct_throws': {w: None for w in WEAPONS},
                    'unattributed_recorded_throws': None, 'observation_status': 'HE_death_drop_event_semantics_unvalidated'}
                unresolved.append({'id': row['id'], 'second': snapshot['second'], 'tick': snapshot['tick']})
            else:
                snapshot['utility'] = utility_summary(releases, row['freeze_end_tick'], snapshot['tick'])
                snapshot['utility']['observation_status'] = 'projectile_release_recovered_v3'
                changed.append({'id': row['id'], 'second': snapshot['second'], 'tick': snapshot['tick']})
    assert len(changed) == 96 and [r['second'] for r in unresolved] == [12, 15, 18, 20]
    assert [r['id'] for r in records] == [r['id'] for r in before]
    for old, new in zip(before, records):
        assert {k: v for k, v in old.items() if k != 'snapshots'} == {k: v for k, v in new.items() if k != 'snapshots'}
        for a, b in zip(old['snapshots'], new['snapshots']):
            assert {k: v for k, v in a.items() if k != 'utility'} == {k: v for k, v in b.items() if k != 'utility'}
        if not old['id'].startswith(target['demo_sha256'] + ':'):
            assert old == new
    groups = context_groups(records)
    complete = {k: int(np.isfinite(v).all(1).sum()) for k, v in groups.items()}
    assert complete == {'equipment': 246, 'score': 246, 'utility': 245}
    guard()
    out.mkdir()
    write(out / 'context.json', records)
    report = {'status': 'complete_conservative_context_v3_export_only', 'protocol_sha256': digest(protocol),
        'parser_version': importlib.metadata.version('demoparser2'), 'windows': len(records),
        'complete_windows_by_group': complete, 'newly_complete_utility_windows': 19,
        'newly_known_utility_snapshots': len(changed), 'remaining_unknown_utility_snapshots': unresolved,
        'remaining_unknown_window': {'round': 20, 'known_seconds': [10], 'unknown_seconds': [12, 15, 18, 20]},
        'source_control_receipt_sha256': digest(ROOT / 'datasets/evaluation/ct_utility_event_investigation.json'),
        'source_control_summary': evidence['controls'], 'source_control_receipt_reused_not_reparsed': True,
        'validated_death_drop_classes': sorted(validated), 'death_drop_counterexamples': 2,
        'target_paired_releases': len(paired), 'target_stationary_gaps_merged': gaps,
        'parent_context_sha256': digest(ROOT / 'output/tagnet/ct_independent_context_v2/context.json'),
        'context_sha256': digest(out / 'context.json'), 'elapsed_seconds': time.monotonic() - started,
        'peak_RAM_MiB': psutil.Process().memory_info().peak_wset / 2**20,
        'limits': ['The two dedicated-event death-drop counterexamples are smoke only; no extrapolation to HE.',
            'Normal-release parity covers3553 records and830 CT query counts across8 Demos; this export reuses that receipt.',
            'The unmatched Molotov firing occurs83 seconds after freeze, and native death precedes its planned release.',
            'No v1/v2 overwrite, source fit, new model evaluation, ranking replay, manuscript edit or semantic label.']}
    write(out / 'report.json', report)
    write(ROOT / 'datasets/evaluation/ct_independent_context_v3_report.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'complete_windows_by_group', 'newly_known_utility_snapshots', 'peak_RAM_MiB')}))


if __name__ == '__main__':
    main()
