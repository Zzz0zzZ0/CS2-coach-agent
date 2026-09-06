import asyncio
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.api.routers import webhooks
from app.services.analysis_pipeline import AnalysisPipeline
from app.services.rag_service import KnowledgeBaseClient
from test_query_boundaries import graph, Store

PAYLOAD = {
    'match_id': 'offline-match', 'map_name': 'Ancient',
    'rounds': [{'round_number':1, 'winner':'T', 'kills':[
        {'killer':'donk','victim':'NiKo','killer_team':'Spirit','victim_team':'Falcons',
         'killer_side':'T','victim_side':'CT','is_first_kill':True,'weapon':'ak47','tick':100}]}],
}


def test_webhook_dispatches_validated_payload(monkeypatch):
    dispatched=[]
    monkeypatch.setattr(webhooks.process_webhook_match_task, 'delay',
        lambda payload: dispatched.append(payload) or SimpleNamespace(id='offline-task'))
    with TestClient(app) as client:
        response=client.post('/api/webhook/match-end',json=PAYLOAD)
    assert response.status_code==200
    assert response.json()['task_id']=='offline-task'
    assert dispatched[0]['match_id']=='offline-match'


def test_offline_analysis_runs_through_verifier(graph):
    from app.domain.match_models import MatchWebhookPayload
    result=asyncio.run(AnalysisPipeline(None,KnowledgeBaseClient(Store(),None),graph).analyze(
        MatchWebhookPayload(**PAYLOAD)))
    assert result.metrics.kills_total==1
    assert result.verification_report['status']=='pass'
    assert result.current_evidence and result.retrieval_evidence
    assert '[C' in result.analyst_report and '[C' in result.coach_advice
    assert result.model_usage=={}
