"""Development cases for deferred source text and version-bound round expansion."""
from copy import deepcopy

import pytest

from app.services import followup_service
from app.services.analysis_runs import AnalysisRunStore
from app.services.followup_service import QuestionUnavailable, answer_question
from app.services.metrics_service import build_current_round_evidence
from test_followup import ask, client, round_data, save


def without_source_detail(answer):
    compact = deepcopy(answer)
    for source in compact['sources']:
        source.pop('content', None)
    for fact in compact['facts']:
        fact.pop('kill_sequence', None)
    return compact


@pytest.mark.parametrize('kind,params', [
    ('opening_losses', {}), ('post_plant_losses', {}),
    ('round', {'round_number': 9}), ('player', {'player': 'alpha'}),
])
def test_compact_preserves_answer_counts_citations_and_provenance(client, kind, params):
    store = save([round_data(3), round_data(9, 'Unknown'), round_data(12, 'T')])
    before = store.path.read_bytes()
    record = store.get('questions')
    default = ask(client, kind, **params)
    full = ask(client, kind, detail='full', **params)
    compact = ask(client, kind, detail='compact', **params)
    assert default.status_code == full.status_code == compact.status_code == 200
    assert default.json() == full.json()
    assert compact.json() == without_source_detail(full.json())
    assert all('content' in source for source in full.json()['sources'])
    assert all('content' not in source for source in compact.json()['sources'])
    assert all('kill_sequence' not in fact for fact in compact.json()['facts'])
    assert compact.json()['budget'] == {'max_steps': 2, 'steps_used': 2, 'model_calls': 0}
    assert store.path.read_bytes() == before
    assert store.get('questions') == record


def test_round_expansion_preserves_source_identity_and_returns_only_selected_round(client, monkeypatch):
    store = save([round_data(3), round_data(9), round_data(12)])
    compact = ask(client, 'opening_losses', detail='compact').json()
    selected = compact['sources'][1]
    calls = []
    original = followup_service.build_current_round_evidence

    def build_selected(match, summary, *, include_content=True):
        calls.append((summary['round_number'], include_content))
        assert summary['round_number'] == 9, 'An unopened round source was materialized'
        return original(match, summary, include_content=include_content)

    monkeypatch.setattr(followup_service, 'build_current_round_evidence', build_selected)
    before = store.path.read_bytes()
    response = ask(client, 'round', round_number=selected['metadata']['round_number'], detail='full',
                   expected_payload_sha256=compact['provenance']['payload_sha256'])
    assert response.status_code == 200
    expanded = response.json()
    assert expanded['status'] == 'found'
    assert expanded['provenance'] == compact['provenance']
    assert expanded['matched_rounds'] == 1 and len(expanded['sources']) == len(expanded['facts']) == 1
    assert without_source_detail(expanded)['sources'] == [selected]
    assert 'Current demo round 9' in expanded['sources'][0]['content']
    assert expanded['facts'][0]['round_number'] == 9
    assert expanded['facts'][0]['kill_sequence'][0]['killer'] == 'alpha'
    assert calls == [(9, True)]
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('detail', ['full', 'compact'])
def test_changed_snapshot_is_rejected_before_querying_or_exposing_new_facts(client, monkeypatch, detail):
    store = save([round_data(3)])
    initial = ask(client, 'opening_losses', detail='compact').json()
    old_hash = initial['provenance']['payload_sha256']
    store.save_input('questions', {'match_id': 'replacement-dev', 'map_name': 'Nuke',
                                 'rounds': [round_data(3, 'T')]})
    assert store.get('questions')['metadata']['payload_sha256'] != old_hash

    def forbidden(*args, **kwargs):
        pytest.fail('A changed snapshot reached the current-match query')

    monkeypatch.setattr(followup_service, 'calculate_metrics', forbidden)
    monkeypatch.setattr(followup_service, 'build_current_round_evidence', forbidden)
    before = store.path.read_bytes()
    response = ask(client, 'round', round_number=3, detail=detail, expected_payload_sha256=old_hash)
    assert response.status_code == 409
    assert set(response.json()) == {'detail'}
    assert '版本已变化' in response.json()['detail']
    assert 'replacement-dev' not in response.text and 'Nuke' not in response.text
    assert store.path.read_bytes() == before


@pytest.mark.parametrize('params', [
    {'detail': ''}, {'detail': 'FULL'}, {'detail': 'summary'},
    {'expected_payload_sha256': ''}, {'expected_payload_sha256': 'a' * 63},
    {'expected_payload_sha256': 'a' * 65}, {'expected_payload_sha256': 'A' * 64},
    {'expected_payload_sha256': 'g' * 64}, {'expected_payload_sha256': '0' * 63 + '\n'},
])
def test_invalid_detail_or_digest_is_rejected_before_reading_storage(client, monkeypatch, params):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid source options reached saved storage')

    monkeypatch.setattr(AnalysisRunStore, 'read_input', forbidden)
    response = ask(client, 'opening_losses', **params)
    assert response.status_code == 422
    assert not AnalysisRunStore().path.exists()
    with pytest.raises(QuestionUnavailable) as error:
        answer_question(AnalysisRunStore(), 'questions', 'opening_losses', **params)
    assert error.value.status_code == 422


def test_compact_step_budget_stops_before_query(client, monkeypatch):
    save([round_data(3)])

    def forbidden(*args, **kwargs):
        pytest.fail('Compact mode exceeded the requested one-step budget')

    monkeypatch.setattr(followup_service, 'calculate_metrics', forbidden)
    response = ask(client, 'opening_losses', detail='compact', max_steps=1)
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'budget_exhausted' and not data['complete']
    assert data['facts'] == data['sources'] == []
    assert data['budget'] == {'max_steps': 1, 'steps_used': 1, 'model_calls': 0}
    assert [event['tool'] for event in data['trace']] == ['read_saved_input']


@pytest.mark.parametrize('count', [1000, 1001])
def test_compact_keeps_round_scope_and_source_limits(client, monkeypatch, count):
    save([round_data(i * 3) for i in range(1, count + 1)])
    calls = []
    original = followup_service.build_current_round_evidence

    def source_summary(match, summary, *, include_content=True):
        calls.append((summary['round_number'], include_content))
        return original(match, summary, include_content=include_content)

    monkeypatch.setattr(followup_service, 'build_current_round_evidence', source_summary)
    data = ask(client, 'post_plant_losses', detail='compact').json()
    if count == 1001:
        assert data['status'] == 'unknown' and not data['complete']
        assert data['facts'] == data['sources'] == []
        assert calls == []
        return
    assert data['status'] == 'found' and data['complete'] and data['truncated']
    assert data['matched_rounds'] == 1000 and data['unknown_rounds'] == 0
    assert len(data['sources']) == len(data['facts']) == 20
    assert calls == [(i * 3, False) for i in range(1, 21)]
    assert [source['citation'] for source in data['sources']] == [f'C{i}' for i in range(2, 22)]
    assert all('content' not in source for source in data['sources'])
    assert all('kill_sequence' not in fact for fact in data['facts'])


def test_player_compact_aggregation_includes_rounds_beyond_display_limit(client):
    save([round_data(i * 3) for i in range(1, 24)])
    full = ask(client, 'player', player='alpha').json()
    compact = ask(client, 'player', player='alpha', detail='compact').json()
    assert compact == without_source_detail(full)
    assert compact['facts'] == [{'player': 'alpha', 'kills': 23, 'deaths': 0, 'first_kills': 23}]
    assert compact['matched_rounds'] == 23 and compact['complete'] and compact['truncated']
    assert len(compact['sources']) == 20


@pytest.mark.parametrize('kind,params,rounds,status', [
    ('opening_losses', {}, [round_data(3, 'Unknown')], 'unknown'),
    ('post_plant_losses', {}, [round_data(3, 'Unknown')], 'unknown'),
    ('post_plant_losses', {}, [round_data(3, 'T')], 'not_found'),
    ('round', {'round_number': 9}, [round_data(3)], 'not_found'),
    ('player', {'player': 'Alpha'}, [round_data(3)], 'unknown'),
    ('opening_losses', {}, [round_data(3), round_data(3)], 'unknown'),
])
def test_compact_does_not_turn_absent_or_ambiguous_evidence_into_facts(client, kind, params, rounds, status):
    save(rounds)
    full = ask(client, kind, **params).json()
    compact = ask(client, kind, detail='compact', **params).json()
    assert compact == full
    assert compact['status'] == status
    assert compact['facts'] == compact['sources'] == []
    assert compact['complete'] == (status == 'not_found')


def test_deferred_round_source_does_not_read_event_narrative_fields():
    source = build_current_round_evidence(
        {'match_id': 'source-dev', 'map_name': 'Mirage'}, {'round_number': 9}, include_content=False)
    assert source['source_id'] == 'current:source-dev:Mirage:9'
    assert source['metadata']['round_number'] == 9
    assert 'content' not in source
