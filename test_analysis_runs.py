import asyncio
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.match_models import MatchWebhookPayload
from app.services.analysis_runs import AnalysisRunStore, RunAlreadyStarted
from app.services.analysis_pipeline import AnalysisPipeline
from app.services import tasks
from app.main import app


def payload():
    return MatchWebhookPayload(match_id='history-fixture', map_name='Mirage', rounds=[{
        'round_number': 1, 'winner': 'T', 'kills': [],
    }])


def offline_worker(monkeypatch):
    monkeypatch.setattr(tasks, 'get_llm', lambda: None)
    monkeypatch.setattr(tasks, 'get_kb_client', lambda: None)
    monkeypatch.setattr(tasks, 'get_graph_client', lambda: None)


def test_completed_report_survives_redis_loss_and_duplicate_delivery(monkeypatch, tmp_path):
    offline_worker(monkeypatch)
    monkeypatch.chdir(tmp_path)
    original = tasks._run_match_analysis(payload(), 'saved-task')
    # A duplicate must not even initialize clients, let alone call the model.
    monkeypatch.setattr(tasks, 'get_llm', lambda: pytest.fail('duplicate execution'))
    assert tasks._run_match_analysis(payload(), 'saved-task') == original
    from app.api.routers import tasks as api
    monkeypatch.setattr(api, 'AsyncResult', lambda *a, **kw: pytest.fail('Redis must not be consulted'))
    client = TestClient(app)
    response = client.get('/api/tasks/saved-task').json()
    assert response['storage'] == 'local' and response['status'] == 'SUCCESS'
    assert response['result'] == original
    assert len(response['metadata']['payload_sha256']) == 64
    assert 'input_json' not in response
    assert client.get('/api/tasks').json()['runs'][0]['task_id'] == 'saved-task'
    events = response['events']
    assert [e['node'] for e in events if e['status'] == 'completed'] == [
        'Initialize', 'Supervisor', 'Tools', 'Router', 'Retrieve', 'Critique', 'Analyst', 'Coach', 'Verifier']
    assert all(e['duration_ms'] >= 0 for e in events if e['status'] == 'completed')
    assert [e for e in events if e['node'] == 'Coach'][-1]['details']['selection_source'] == 'deterministic_fallback'
    with sqlite3.connect(settings.ANALYSIS_RUN_DB) as db:
        assert 'history-fixture' in db.execute('SELECT input_json FROM runs').fetchone()[0]


def test_live_events_are_committed_before_node_finishes(monkeypatch, tmp_path):
    import app.agentic.workflow as workflow
    store = AnalysisRunStore()
    assert store.start('live-task', {})
    seen = []
    def factory(llm):
        async def coach(state):
            saved = AnalysisRunStore().get('live-task')
            seen.append(saved['events'][-1])
            assert saved['status'] == 'STARTED'
            await asyncio.sleep(0)
            return {'coach_advice': 'fixture [C1]'}
        return coach
    monkeypatch.setattr(workflow, 'create_coach_node', factory)
    result = asyncio.run(AnalysisPipeline(None, None).analyze(payload(), lambda e: store.event('live-task', e)))
    assert seen[0]['node'] == 'Coach' and seen[0]['status'] == 'started'
    assert result.execution_trace[-1]['node'] == 'Verifier'
    assert result.execution_trace[-1]['status'] == 'completed'


def test_node_failure_retains_partial_trace_and_does_not_replay(monkeypatch, tmp_path):
    import app.agentic.workflow as workflow
    offline_worker(monkeypatch)
    monkeypatch.chdir(tmp_path)
    def factory(llm):
        async def coach(state):
            raise ValueError('SECRET must never reach history')
        return coach
    monkeypatch.setattr(workflow, 'create_coach_node', factory)
    with pytest.raises(ValueError):
        tasks._run_match_analysis(payload(), 'failed-task')
    saved = AnalysisRunStore().get('failed-task')
    assert saved['status'] == 'FAILURE' and saved['error'] == 'ValueError'
    assert saved['events'][-1]['node'] == 'Coach' and saved['events'][-1]['status'] == 'failed'
    assert not any(e['node'] == 'Verifier' for e in saved['events'])
    assert 'SECRET' not in str(saved)
    with pytest.raises(RunAlreadyStarted):
        tasks._run_match_analysis(payload(), 'failed-task')
    assert AnalysisRunStore().get('failed-task') == saved


def test_interrupted_and_concurrent_claims_never_auto_resume():
    from concurrent.futures import ThreadPoolExecutor
    store = AnalysisRunStore()
    # Initialize schema, then race separate connections to the same task ID.
    assert store.start('schema', {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: AnalysisRunStore().start('same-task', {}), range(2)))
    assert sorted(claims) == [False, True]
    with pytest.raises(RunAlreadyStarted):
        tasks._run_match_analysis(payload(), 'same-task')
    assert store.get('same-task')['status'] == 'STARTED'
    assert store.get('same-task')['events'] == []


def test_parse_failure_is_durable_and_retained_input_is_not_deleted(monkeypatch, tmp_path):
    demo = tmp_path / 'invalid.dem'
    demo.write_bytes(b'not a demo')
    monkeypatch.setattr(tasks, 'TacticalDemoParser', lambda path: Mock(parse_to_dict=lambda: {}))
    monkeypatch.setattr(tasks.parse_and_analyze_demo_task, 'update_state', lambda **kw: None)
    tasks.parse_and_analyze_demo_task.push_request(id='bad-demo')
    try:
        with pytest.raises(ValueError):
            tasks.parse_and_analyze_demo_task.run(str(demo))
    finally:
        tasks.parse_and_analyze_demo_task.pop_request()
    saved = AnalysisRunStore().get('bad-demo')
    assert saved['status'] == 'FAILURE'
    assert len(saved['metadata']['demo_sha256']) == 64
    assert [e['status'] for e in saved['events']] == ['started', 'failed']
    assert demo.exists()


def test_retrieval_attempts_have_separate_durations(monkeypatch):
    import app.agentic.workflow as workflow
    attempts = []
    def factory(llm):
        async def critique(state):
            attempt = len(attempts) + 1
            attempts.append(attempt)
            return {'critique_score': 0 if attempt == 1 else 1, 'retry_count': attempt,
                    'retrieval_available': True, 'retrieval_retry_tasks': ['opening_duel'] if attempt == 1 else []}
        return critique
    monkeypatch.setattr(workflow, 'create_critique_node', factory)
    result = asyncio.run(AnalysisPipeline(None, None).analyze(payload()))
    retrieval = [e for e in result.execution_trace if e['node'] == 'Retrieve']
    assert [(e['attempt'], e['status']) for e in retrieval] == [
        (1, 'started'), (1, 'completed'), (2, 'started'), (2, 'completed')]


def test_history_read_is_noncreating_and_corrupt_storage_returns_503():
    from pathlib import Path
    store = AnalysisRunStore()
    assert store.get('missing') is None and store.recent() == []
    assert not store.path.exists()
    Path(settings.ANALYSIS_RUN_DB).write_text('corrupt')
    response = TestClient(app).get('/api/tasks/unknown')
    assert response.status_code == 503
    assert 'corrupt' not in response.text
    assert TestClient(app).get('/api/tasks?limit=101').status_code == 422
