import asyncio
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.prompts import PromptTemplate

from app.core.llm_budget import BudgetedChatModel, ModelBudget, ModelCallStopped
from app.agentic.nodes.coach_node import _select_priorities
from app.core import providers
from app.core.config import settings
from app.main import app


class Model:
    def __init__(self, total=15, error=None):
        self.calls, self.total, self.error = 0, total, error
        self.schemas = None

    def bind_tools(self, schemas):
        self.schemas = schemas
        return self

    def invoke(self, prompt, config=None):
        self.calls += 1
        if self.error:
            raise self.error
        usage = None if self.total is None else {'input_tokens': self.total-5, 'output_tokens':5, 'total_tokens':self.total}
        return AIMessage(content='ok', usage_metadata=usage,
                         tool_calls=[{'name':'select_coaching_priorities','args':{
                             'priority_ids':['opening_followup','utility_review']},'id':'test'}])

    async def ainvoke(self, prompt, config=None):
        return self.invoke(prompt, config)


def wrapped(tmp_path, model=None, tokens=30000, calls=100):
    budget = ModelBudget(tmp_path/'budget.sqlite', tokens, calls)
    model = model or Model()
    return BudgetedChatModel(model, budget, 512, 1), model, budget


def test_sync_chain_and_async_tool_share_persistent_usage(tmp_path):
    llm, model, budget = wrapped(tmp_path)
    assert (PromptTemplate.from_template('Hello {name}') | llm).invoke({'name':'world'}).content == 'ok'
    choices, source, usage = asyncio.run(_select_priorities(llm, {}))
    assert choices == ['opening_followup','utility_review'] and source == 'qwen_tool_call'
    assert usage['total_tokens'] == 15 and model.schemas[0]['type'] == 'function'
    restored = ModelBudget(budget.path,30000,100).status()
    assert restored['calls'] == 2 and restored['reported_tokens'] == 30
    assert restored['remaining_local_allowance'] == 29970 and restored['accounting_complete']
    assert restored['provider_remaining_tokens'] is None
    with sqlite3.connect(budget.path) as db:
        assert db.execute('SELECT count(*) FROM calls WHERE status="completed"').fetchone()[0] == 2
        assert 'Hello world' not in str(db.execute('SELECT * FROM calls').fetchall())


@pytest.mark.parametrize('tokens,calls', [(1,100),(30000,0),(0,100)])
def test_preflight_limits_never_contact_model(tmp_path,tokens,calls):
    llm, model, budget = wrapped(tmp_path,tokens=tokens,calls=calls)
    assert asyncio.run(_select_priorities(llm,{}))[1] == 'deterministic_fallback'
    assert model.calls == budget.status()['calls'] == 0
    assert budget.status()['reported_tokens'] == 0


def test_count_limit_and_configuration_change_cannot_reset_ledger(tmp_path):
    llm, model, budget = wrapped(tmp_path,calls=1)
    llm.invoke('one')
    with pytest.raises(ModelCallStopped,match='budget_exhausted'):
        llm.invoke('two')
    assert model.calls == 1
    changed = ModelBudget(budget.path,60000,200)
    assert changed.status()['stop_reason'] == 'configuration_mismatch'
    with pytest.raises(ModelCallStopped,match='configuration_mismatch'):
        changed.reserve(4000,'hash')


@pytest.mark.parametrize('failure', ['timeout','quota','missing','over_estimate'])
def test_failure_stops_later_calls_and_preserves_uncertain_allowance(tmp_path,failure):
    error = TimeoutError('SECRET provider request data') if failure == 'timeout' else None
    if failure == 'quota':
        error = RuntimeError('SECRET provider quota body')
        error.status_code = 429
    llm, model, budget = wrapped(tmp_path, Model(None if failure == 'missing' else 40000 if failure == 'over_estimate' else 15,error))
    with pytest.raises(ModelCallStopped) as caught:
        llm.invoke('SECRET prompt')
    assert 'SECRET' not in str(caught.value)
    with pytest.raises(ModelCallStopped):
        llm.invoke('next')
    assert model.calls == 1 and budget.status()['status'] == 'stopped'
    if failure != 'over_estimate':
        assert budget.status()['reported_tokens'] == 0
        assert budget.status()['unsettled_allowance'] > 0
        assert not budget.status()['accounting_complete']
    else:
        assert budget.status()['reported_tokens'] == 40000
        assert budget.status()['remaining_local_allowance'] == 0
    with sqlite3.connect(budget.path) as db:
        assert 'SECRET' not in str(db.execute('SELECT * FROM calls').fetchall())


def test_async_timeout_and_cancellation_leave_durable_stop(tmp_path):
    async def scenario():
        class HangingModel(Model):
            async def ainvoke(self, prompt, config=None):
                self.calls += 1
                await asyncio.Event().wait()
        llm, model, budget = wrapped(tmp_path/'timeout',HangingModel())
        llm.timeout = 0.02
        with pytest.raises(ModelCallStopped,match='request_failed'):
            await llm.ainvoke('timeout')
        assert model.calls == 1 and budget.status()['status'] == 'stopped'
        llm, model, budget = wrapped(tmp_path/'cancel',HangingModel())
        running = asyncio.create_task(llm.ainvoke('cancel'))
        while not model.calls:
            await asyncio.sleep(0)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert budget.status()['stop_reason'] == 'cancelled'
        with pytest.raises(ModelCallStopped):
            await llm.ainvoke('no retry')
        assert model.calls == 1
    asyncio.run(scenario())


def test_processes_cannot_overbook_or_replay_pending_request(tmp_path):
    script = '''import sys
from app.core.llm_budget import ModelBudget, ModelCallStopped
try:
    ModelBudget(sys.argv[1],30000,100).reserve(3000,'test')
    print('reserved')
except ModelCallStopped as error:
    print(str(error))
'''
    path = tmp_path/'budget.sqlite'
    processes = [subprocess.Popen([sys.executable,'-c',script,str(path)],stdout=subprocess.PIPE,text=True) for _ in range(3)]
    results = [p.communicate(timeout=30)[0].strip() for p in processes]
    assert all(p.returncode == 0 for p in processes)
    assert sorted(results) == ['pending','pending','reserved']
    budget = ModelBudget(path,30000,100)
    assert budget.status()['calls'] == 1 and budget.status()['unsettled_allowance'] == 3000
    with pytest.raises(ModelCallStopped,match='pending'):
        budget.reserve(3000,'retry')


def test_unavailable_ledger_and_call_overrides_fail_closed(tmp_path):
    llm, model, budget = wrapped(tmp_path)
    with pytest.raises(ModelCallStopped,match='unsupported_call_options'):
        llm.invoke('prompt',max_tokens=100000)
    budget.path.write_text('broken sqlite')
    with pytest.raises(ModelCallStopped,match='ledger_unavailable'):
        llm.invoke('prompt')
    assert model.calls == 0


def test_provider_configuration_refresh_and_read_only_status(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'LLM_BUDGET_DB',str(tmp_path/'budget.sqlite'))
    monkeypatch.setattr(settings,'LLM_BUDGET_TOKENS',30000)
    monkeypatch.setattr(settings,'LLM_BUDGET_MAX_CALLS',100)
    monkeypatch.setattr(providers,'get_configured_api_key',lambda:'sk-test-key-not-used-for-network')
    monkeypatch.setattr(providers,'_llm_instance',None)
    monkeypatch.setattr(providers,'_llm_key_fingerprint',None)
    constructed = []
    monkeypatch.setattr(providers,'ChatOpenAI',lambda **kw: constructed.append(kw) or Model())
    client = TestClient(app)
    state = client.get('/api/settings/llm/budget').json()
    assert state['calls'] == 0 and state['provider_remaining_tokens'] is None
    assert not (tmp_path/'budget.sqlite').exists()
    first = providers.get_llm()
    monkeypatch.setattr(settings,'LLM_MAX_TOKENS',512)
    second = providers.get_llm()
    assert second is not first and second.max_tokens == 512
    assert all(row['max_retries'] == 0 for row in constructed)
    monkeypatch.setattr(settings,'MODEL_NAME','other-model')
    assert providers.get_llm() is None
    assert len(constructed) == 2
    (tmp_path/'budget.sqlite').write_text('broken')
    assert client.get('/api/settings/llm/budget').status_code == 503


def test_budget_rejection_preserves_full_analysis_pipeline(tmp_path):
    from app.services.analysis_pipeline import AnalysisPipeline
    from app.domain.match_models import MatchWebhookPayload
    llm, model, budget = wrapped(tmp_path,tokens=1)
    payload = MatchWebhookPayload(match_id='budget-fixture',map_name='de_dust2',rounds=[{
        'round_number':1, 'winner':'T', 'kills':[]
    }])
    result = asyncio.run(AnalysisPipeline(llm,None).analyze(payload))
    assert result.metrics.rounds_total == 1 and result.current_evidence
    assert result.coach_decision['selection_source'] == 'deterministic_fallback'
    assert '[C1]' in result.coach_advice
    assert model.calls == budget.status()['calls'] == 0


def test_key_rotation_keeps_existing_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'LLM_BUDGET_DB',str(tmp_path/'budget.sqlite'))
    monkeypatch.setattr(providers,'_llm_instance',None)
    monkeypatch.setattr(providers,'_llm_key_fingerprint',None)
    monkeypatch.setattr(providers,'ChatOpenAI',lambda **kw: Model())
    monkeypatch.setattr(providers,'get_configured_api_key',lambda:'sk-test-key-one')
    first = providers.get_llm()
    first.invoke('first')
    monkeypatch.setattr(providers,'get_configured_api_key',lambda:'sk-test-key-two')
    second = providers.get_llm()
    assert second is not first
    assert second.budget.status()['calls'] == 1
    assert second.budget.status()['reported_tokens'] == 15
