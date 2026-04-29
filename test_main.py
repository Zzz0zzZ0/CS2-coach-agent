import logging
from fastapi.testclient import TestClient
from app.core.celery_app import celery_app
celery_app.conf.update(task_always_eager=True)
from app.main import app

MOCK_PAYLOAD = {
    "match_id": "test-match-123",
    "map_name": "de_dust2",
    "rounds": [
        {"round": 1, "winner": "T"},
        {"round": 2, "winner": "CT"}
    ],
    "some_unknown_field": "This should be caught by extra",
    "extra_data": {
        "source": "FACEIT"
    }
}

def test_webhook_match_end():
    client = TestClient(app)
    response = client.post("/api/webhook/match-end", json=MOCK_PAYLOAD)
    
    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json.get("status") == "processing_in_mq"
    assert "task_id" in resp_json
    print(f"Test passed! Returned 200 processing with task_id: {resp_json['task_id']}")

if __name__ == "__main__":
    test_webhook_match_end()
