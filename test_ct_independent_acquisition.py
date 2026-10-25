import pytest

from scripts.acquire_ct_independent_demos import selected_member


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
