"""模拟示例：试点查询和候选必须隔离整场系列赛。"""

import pytest

from scripts.build_ct_semantic_pilot import candidate_library, select_queries


def test_query_selection_is_reproducible_and_keeps_two_series_per_map():
    records = [{"id": str(i), "series": s, "map": m} for i, (s, m) in enumerate([
        ("A", "x"), ("B", "x"), ("C", "x"), ("A", "y"), ("D", "y")])]
    patches = {r["id"]: "14174" if r["series"] != "A" else "14165" for r in records}
    chosen = select_queries(records, patches)
    assert chosen == select_queries(list(reversed(records)), patches)
    assert {r["series"] for r in chosen if r["map"] == "x"} == {"B", "C"}
    assert len(chosen) == 4
    with pytest.raises(ValueError):
        select_queries(records[:1], patches)


def test_library_excludes_whole_target_map_series_and_old_patch_rows():
    query = {"id": "q", "series": "A", "map": "x"}
    records = [query, {"id": "leak", "series": "A", "map": "y"},
        {"id": "target", "series": "B", "map": "x"}, {"id": "leak2", "series": "B", "map": "z"},
        {"id": "old", "series": "C", "map": "z"}] + [{"id": str(i), "series": "D", "map": "y"} for i in range(5)]
    patches = {r["id"]: "14165" if r["id"] == "old" else "14174" for r in records}
    result = candidate_library(query, records, patches)
    assert {r["id"] for r in result} == {str(i) for i in range(5)}
    with pytest.raises(ValueError):
        candidate_library(query, records[:5], patches)
