import logging
from fastapi.testclient import TestClient
from main import app

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
    assert response.json() == {"status": "processing"}
    print("Test passed! Returned 200 processing.")

if __name__ == "__main__":
    test_webhook_match_end()
