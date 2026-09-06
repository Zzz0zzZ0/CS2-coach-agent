from pathlib import Path

from scripts.seed_knowledge import _match_id_from_path


def test_match_id_from_downloaded_demo_name():
    path = Path("BLAST_Open_FURIA_vs_Vitality_2396948_map1.dem")
    assert _match_id_from_path(path) == "2396948"


def test_match_id_from_legacy_hyphenated_name():
    path = Path("furia-vitality-2396948-map1.dem")
    assert _match_id_from_path(path) == "2396948"


def test_staging_collection_collision_never_drops_or_embeds(monkeypatch):
    import pytest
    from scripts import seed_knowledge as seed

    class ExistingCollection:
        def has_collection(self, name):
            return True

    monkeypatch.setattr(seed, 'MilvusClient', lambda **kwargs: ExistingCollection())
    monkeypatch.setattr(seed, 'get_embeddings', lambda: pytest.fail('Collision must fail before embedding'))
    with pytest.raises(ValueError, match='Staging collection already exists'):
        seed.seed_milvus_db([], collection_name='existing_staging')
