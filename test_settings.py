import stat

from fastapi.testclient import TestClient

from app.core import providers
from app.core.config import settings
from app.main import app


def test_runtime_llm_key_is_write_only_and_shared_by_file(tmp_path, monkeypatch):
    key_file = tmp_path / "runtime" / "dashscope_api_key"
    monkeypatch.setattr(settings, "DASHSCOPE_KEY_FILE", str(key_file))
    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    providers._llm_instance = None
    providers._llm_key_fingerprint = None
    client = TestClient(app)

    assert client.get("/api/settings/llm").json() == {
        "configured": False, "provider": "DashScope",
    }
    assert client.put("/api/settings/llm/key", json={"api_key": "too-short"}).status_code == 422
    invalid_key = "z" * 513
    invalid_response = client.put("/api/settings/llm/key", json={"api_key": invalid_key})
    assert invalid_response.status_code == 422
    assert invalid_key not in invalid_response.text

    api_key = "sk-test-1234567890abcdefghijklmnop"
    response = client.put("/api/settings/llm/key", json={"api_key": api_key})
    assert response.status_code == 200
    assert response.json() == {"configured": True, "provider": "DashScope"}
    assert api_key not in response.text
    assert providers.get_configured_api_key() == api_key
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert client.get("/api/settings/llm").json()["configured"] is True

    calls = []
    monkeypatch.setattr(providers, "ChatOpenAI", lambda **kwargs: calls.append(kwargs) or object())
    first_llm = providers.get_llm()
    assert calls[-1]["model"] == "qwen3.8-flash"
    assert calls[-1]["timeout"] == 120
    assert calls[-1]["max_tokens"] == 1400
    assert calls[-1]["max_retries"] == 0
    assert calls[-1]["extra_body"] == {"enable_thinking": False}
    providers.save_runtime_api_key("sk-test-0987654321ponmlkjihgfedcba")
    assert providers.get_llm() is not first_llm

    remote_client = TestClient(app, client=("192.0.2.1", 50000))
    assert remote_client.put(
        "/api/settings/llm/key", json={"api_key": api_key},
    ).status_code == 403
