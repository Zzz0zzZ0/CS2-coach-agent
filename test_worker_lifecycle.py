import asyncio

from langchain_core.messages import AIMessage

from app.core.llm_budget import BudgetedChatModel, ModelBudget
from app.domain.match_models import MatchWebhookPayload
from app.services import tasks


def test_consecutive_worker_tasks_keep_async_model_connections_alive(tmp_path, monkeypatch):
    class PooledModel:
        loop = None

        def bind_tools(self, schemas):
            return self

        async def ainvoke(self, prompt, config=None):
            current = asyncio.get_running_loop()
            if self.loop is not None:
                # A cached TLS connection belongs to the loop that opened it.
                assert not self.loop.is_closed()
                assert self.loop is current
            self.loop = current
            return AIMessage(content='', tool_calls=[{
                'name': 'select_coaching_priorities', 'id': 'local-fixture',
                'args': {'priority_ids': ['opening_followup', 'post_plant']},
            }], usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15})

    budget = ModelBudget(tmp_path / 'budget.sqlite', 30000, 100)
    llm = BudgetedChatModel(PooledModel(), budget, 1400, 120)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tasks, 'get_llm', lambda: llm)
    monkeypatch.setattr(tasks, 'get_kb_client', lambda: None)
    monkeypatch.setattr(tasks, 'get_graph_client', lambda: None)
    payload = MatchWebhookPayload(match_id='local-fixture', map_name='Mirage', rounds=[{
        'round_number': 1, 'winner': 'T', 'kills': [],
    }])
    for task_id in ('first', 'second'):
        result = tasks._run_match_analysis(payload, task_id)
        assert result['analysis']['coach_decision']['selection_source'] == 'qwen_tool_call'
        assert result['analysis']['model_usage']['total_tokens'] == 15
        assert result['knowledge_task_id'] is None
    assert budget.status()['status'] == 'ready'
    assert budget.status()['reported_tokens'] == 30
    assert budget.status()['calls'] == 2
