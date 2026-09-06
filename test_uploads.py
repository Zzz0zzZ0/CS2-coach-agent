from fastapi.testclient import TestClient

from app.api.routers import uploads
from app.main import app


def test_uploaded_demo_is_scheduled_for_cleanup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    class Task:
        id = "task-1"

    def delay(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Task()

    monkeypatch.setattr(uploads.parse_and_analyze_demo_task, "delay", delay)
    response = TestClient(app).post(
        "/api/upload-demo",
        files={"file": ("match.dem", b"demo", "application/octet-stream")},
        data={"analysis_mode": "demo_forensic"},
    )

    assert response.status_code == 200
    assert captured["kwargs"]["auto_delete"] is True
