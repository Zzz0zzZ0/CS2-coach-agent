from pathlib import Path

from scripts.seed_knowledge import _match_id_from_path


def test_match_id_from_downloaded_demo_name():
    path = Path("BLAST_Open_FURIA_vs_Vitality_2396948_map1.dem")
    assert _match_id_from_path(path) == "2396948"


def test_match_id_from_legacy_hyphenated_name():
    path = Path("furia-vitality-2396948-map1.dem")
    assert _match_id_from_path(path) == "2396948"
