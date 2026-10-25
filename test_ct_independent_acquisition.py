import pytest

from scripts.acquire_ct_independent_demos import selected_member, resolved_primary


def test_select_only_requested_regular_archive_member():
    listing = ('-rw-r--r-- 0 0 0 100 May 20 2026 match-m1-dust2.dem\n'
               '-rw-r--r-- 0 0 0 200 May 20 2026 match-m2-nuke.dem')
    assert selected_member(listing, 'de_nuke') == ('match-m2-nuke.dem', 200)
    for unsafe in ('../match-m1-dust2.dem', '/match-m1-dust2.dem', 'C:\\match-m1-dust2.dem'):
        with pytest.raises(ValueError, match='Unsafe'):
            selected_member(f'-rw-r--r-- 0 0 0 100 May 20 2026 {unsafe}', 'de_dust2')
    with pytest.raises(ValueError, match='Unsafe'):
        selected_member('lrwxrwxrwx 0 0 0 100 May 20 2026 match-dust2.dem', 'de_dust2')
    with pytest.raises(ValueError, match='exactly one'):
        selected_member(listing, 'de_mirage')
    split = listing.replace('dust2.dem','mirage-p1.dem').replace('nuke.dem','mirage-p2.dem')
    with pytest.raises(ValueError, match='exactly one'):
        selected_member(split, 'de_mirage')


def test_only_prelisted_compatible_replacement_is_allowed():
    original={'match_id':'1','event_id':10,'selected_map':'de_mirage'}
    alternate={**original,'match_id':'2','replaceable_primary_match_ids':['1']}
    cohort={'primary':[original],'alternates':[alternate]}
    assert resolved_primary(cohort,{'1':{'match_id':'2','reason':'split map'}})==[alternate]
    with pytest.raises(AssertionError):
        resolved_primary(cohort,{'9':{'match_id':'2','reason':'invalid original'}})
    alternate['event_id']=11
    with pytest.raises(AssertionError):
        resolved_primary(cohort,{'1':{'match_id':'2','reason':'wrong event'}})
