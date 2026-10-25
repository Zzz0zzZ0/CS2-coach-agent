from collections import Counter

import pytest

from scripts.prepare_ct_independent_cohort import EVENTS, MAPS, choose_cohort


def test_cohort_selection_respects_maps_events_and_unique_series():
    candidates = [{"match_id": f"{event}_{name}", "event_id": event, "played_maps": [name]}
                  for event in EVENTS for name in MAPS]
    chosen = choose_cohort(candidates)
    assert len(chosen) == 12
    assert Counter(row['selected_map'] for row in chosen) == {name: 2 for name in MAPS}
    assert Counter(row['event_id'] for row in chosen) == {event: 4 for event in EVENTS}
    with pytest.raises(RuntimeError, match='infeasible'):
        choose_cohort([row for row in candidates if row['played_maps'][0] != 'de_nuke'])
