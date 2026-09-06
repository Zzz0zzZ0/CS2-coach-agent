import asyncio
import json
from types import SimpleNamespace

import pytest
from scripts import evaluate_coach_blind as experiment
from app.services.metrics_service import calculate_metrics, build_current_match_evidence


class FakeModel:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, prompt):
        self.calls += 1
        if self.fail:
            raise TimeoutError('test-only timeout')
        return SimpleNamespace(tool_calls=[{'name':'select_coaching_priorities',
            'args':{'priority_ids':['opening_followup','utility_review']}}],
            usage_metadata={'input_tokens':10,'output_tokens':5,'total_tokens':15})


@pytest.fixture
def frozen(tmp_path):
    directory = tmp_path / 'frozen'
    directory.mkdir()
    cases = []
    for index, (match, map_name) in enumerate([('m1','Dust2'),('m1','Mirage'),('m2','Nuke')], 1):
        metrics = calculate_metrics([{'round_number':1,'winner':'T','kills':[
            {'killer':'entry','victim':'defender','killer_team':'Alpha','victim_team':'Bravo',
             'killer_side':'T','victim_side':'CT','is_first_kill':True,'tick':100}]}])
        case = {'case_id':f'case-{index:02}', 'match_id':match, 'map_name':map_name, 'metrics':metrics}
        case['current_evidence'] = build_current_match_evidence(case, metrics)
        cases.append(case)
    experiment.save(directory/'inputs.json', cases)
    experiment.save(directory/'manifest.json', {'model':experiment.MODEL,'inputs_sha256':experiment.digest(directory/'inputs.json'),
        'harness_sha256':experiment.digest(experiment.__file__),
        'implementation_sha256':{path:experiment.digest(experiment.ROOT/path) for path in experiment.SOURCES},
        'reserved_token_budget':30000, 'max_calls':3})
    return directory


def test_coach_blind_run_records_usage_and_keeps_identity_out_of_packet(frozen,tmp_path):
    model = FakeModel()
    report = asyncio.run(experiment.run(frozen,tmp_path/'run',model))
    assert model.calls == report['calls'] == 3
    assert report['reported_tokens'] == 45
    assert report['quality_metrics'] is None
    assert report['status'] == 'awaiting_human_review'
    packet = json.loads((tmp_path/'run/review/packet.json').read_text())
    assert all(set(case['candidates']) == {'A','B'} for case in packet)
    assert all('selection_source' not in case and 'usage' not in case for case in packet)
    assert not (tmp_path/'run/review/method_key.json').exists()
    with pytest.raises(FileExistsError):
        asyncio.run(experiment.run(frozen,tmp_path/'run',model))
    assert model.calls == 3


def test_failure_or_unknown_usage_is_not_counted_as_model_gain(frozen,tmp_path):
    model = FakeModel(fail=True)
    report = asyncio.run(experiment.run(frozen,tmp_path/'run',model))
    assert model.calls == 1
    assert report['status'] == 'stopped'
    assert not report['accounting_complete']
    assert report['quality_metrics'] is None
    assert not (tmp_path/'run/review').exists()
    assert (tmp_path/'run/case-01.attempt.json').exists()


def test_budget_refuses_call_before_network(tmp_path):
    model = FakeModel()
    meter = experiment.MeteredModel(model,tmp_path,budget=1,max_calls=6)
    priorities, source, usage = asyncio.run(experiment._select_priorities(meter,{}))
    assert source == 'deterministic_fallback'
    assert model.calls == 0
    assert meter.error_type == 'LocalBudgetLimit'


def test_modified_frozen_input_never_calls_model(frozen,tmp_path):
    (frozen/'inputs.json').write_text('[]')
    model = FakeModel()
    with pytest.raises(ValueError,match='Frozen inputs'):
        asyncio.run(experiment.run(frozen,tmp_path/'run',model))
    assert model.calls == 0


def test_blank_review_is_pending_and_valid_fixture_scores_weight_matches(frozen,tmp_path):
    asyncio.run(experiment.run(frozen,tmp_path/'run',FakeModel()))
    packet, key = tmp_path/'run/review/packet.json', tmp_path/'run/method_key.json'
    reviews = [tmp_path/f'run/review/reviewer_{index}.json' for index in (1,2)]
    pending = experiment.score(packet,key,reviews)
    assert pending['status'] == 'pending_review'
    assert pending['quality_metrics'] is None
    assignments = json.loads(key.read_text())['assignments']
    for index, path in enumerate(reviews):
        review = json.loads(path.read_text())
        review.update(reviewer_id=f'test-fixture-{index}',reviewed_at='2026-09-06',
                      independent_review_attestation=True,method_key_not_seen_attestation=True)
        for case_index, row in enumerate(review['ratings']):
            for label, method in assignments[row['case_id']].items():
                row[label] = dict.fromkeys(experiment.DIMENSIONS, [5,1,5][case_index] if method=='model' else 3)
            row.update(preference='tie',rationale='Synthetic test fixture, not human review')
        path.write_text(json.dumps(review))
    result = experiment.score(packet,key,reviews)
    assert result['quality_metrics']['mean_match_delta']['priority_relevance'] == 1
    assert result['matches'] == 2
    assert result['maps'] == 3
    assert result['quality_metrics']['preference_counts']['tie'] == 6
    bad = json.loads(reviews[1].read_text())
    bad['reviewer_id'] = 'test-fixture-0'
    reviews[1].write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='Duplicate reviewer'):
        experiment.score(packet,key,reviews)


def test_review_cannot_score_different_packet_or_reversed_key(frozen,tmp_path):
    asyncio.run(experiment.run(frozen,tmp_path/'run',FakeModel()))
    packet, key = tmp_path/'run/review/packet.json', tmp_path/'run/method_key.json'
    reviews = [tmp_path/'run/review/reviewer_1.json']
    original = json.loads(key.read_text())
    original['assignments']['case-01'] = {'A':'rule','B':'rule'}
    key.write_text(json.dumps(original))
    with pytest.raises(ValueError,match='another packet'):
        experiment.score(packet,key,reviews)
