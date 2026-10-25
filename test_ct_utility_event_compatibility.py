import pandas as pd
import pytest
from scripts.repair_ct_independent_utility import projectile_release_events


def example():
    owner = 76561198028292758
    points = pd.DataFrame([
        {'grenade_type': 'CMolotovProjectile', 'grenade_entity_id': 17, 'tick': tick,
         'steamid': owner, 'x': 1., 'y': 2., 'z': 3.}
        for tick in [107, 108, 214, 215]])
    fired = pd.DataFrame([{'tick': 100, 'user_steamid': str(owner), 'weapon': 'weapon_incgrenade'},
                          {'tick': 200, 'user_steamid': str(owner), 'weapon': 'weapon_molotov'},
                          {'tick': 150, 'user_steamid': str(owner), 'weapon': 'weapon_ak47'}])
    return points, fired


def test_recovers_actual_births_reused_entities_subtypes_and_precise_owner_ids():
    points, fired = example()
    result = projectile_release_events(points, fired)
    assert result['tick'].tolist() == [107, 214]
    assert result['weapon'].tolist() == ['incgrenade', 'molotov']
    assert result['user_steamid'].tolist() == ['76561198028292758'] * 2
    assert result['fire_tick'].tolist() == [100, 200]


def test_incomplete_pairs_are_not_imputed():
    points, fired = example()
    with pytest.raises(ValueError, match='counts disagree'):
        projectile_release_events(points.iloc[:2], fired)


def test_noncausal_pairs_are_rejected():
    points, fired = example()
    fired.loc[0, 'tick'] = 110
    with pytest.raises(ValueError, match='order'):
        projectile_release_events(points, fired)


def test_held_grenades_cannot_be_counted_as_throws():
    points, fired = example()
    points['grenade_type'] = 'CIncendiaryGrenade'
    with pytest.raises(ValueError, match='held grenades'):
        projectile_release_events(points, fired)


def test_stationary_projectile_after_a_globally_missing_tick_is_not_a_new_throw():
    points, fired = example()
    points['tick'] = [107, 108, 110, 111]
    result = projectile_release_events(points, fired.iloc[:1])
    assert result['tick'].tolist() == [107]
    assert result.attrs['stationary_recording_gaps_merged'] == 1


def test_unpaired_projectile_is_ignored_only_outside_frozen_query_intervals():
    points, fired = example()
    extra = points.iloc[-1:].copy()
    extra['tick'] = 300
    extra['grenade_entity_id'] = 18
    points = pd.concat([points, extra], ignore_index=True)
    result = projectile_release_events(points, fired, intervals=[(90, 220)])
    assert result['tick'].tolist() == [107, 214]
    assert result.attrs['unpaired_projectiles_outside_queries'] == 1
    uncertain = projectile_release_events(points, fired, intervals=[(90, 320)])
    assert uncertain['tick'].tolist() == [107, 214]
    assert uncertain.attrs['unpaired_projectiles_inside_queries'] == [
        {'tick': 300, 'user_steamid': '76561198028292758', 'grenade_type': 'CMolotovProjectile'}]
