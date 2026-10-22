import stat
import os
import csv
import re
import subprocess

import pytest

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
    if os.name == "nt":
        options = {"capture_output": True, "check": True, "timeout": 10, "creationflags": subprocess.CREATE_NO_WINDOW}
        acl_file = tmp_path / "key.acl"
        subprocess.run(["icacls.exe", str(key_file), "/save", str(acl_file), "/q"], **options)
        identity = subprocess.run(["whoami.exe", "/user", "/fo", "csv", "/nh"], **options)
        sid = next(csv.reader(identity.stdout.decode("utf-8", errors="replace").splitlines()))[1]
        sddl = acl_file.read_text(encoding="utf-16-le").splitlines()[1]
        assert re.fullmatch(r"D:P(?:AI)?\(A;;FA;;;" + re.escape(sid) + r"\)", sddl)
    else:
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


def test_permission_failure_leaves_existing_key_and_no_secret_temporary(tmp_path, monkeypatch):
    key_file = tmp_path / "key"
    key_file.write_text("previous-key", encoding="utf-8")
    monkeypatch.setattr(settings, "DASHSCOPE_KEY_FILE", str(key_file))

    def reject(descriptor, path):
        assert os.fstat(descriptor).st_size == 0
        raise PermissionError("simulated permission failure")

    monkeypatch.setattr(providers, "_restrict_runtime_key_file", reject)
    with pytest.raises(PermissionError):
        providers.save_runtime_api_key("sk-test-1234567890abcdefghijklmnop")
    assert key_file.read_text() == "previous-key"
    assert list(tmp_path.iterdir()) == [key_file]


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL command failure contract")
@pytest.mark.parametrize("problem", ["identity", "timeout", "permissions"])
def test_windows_permission_errors_fail_before_persisting_key(tmp_path, monkeypatch, problem):
    key_file = tmp_path / "key"
    monkeypatch.setattr(settings, "DASHSCOPE_KEY_FILE", str(key_file))

    def run(command, **kwargs):
        if problem == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if command[0] == "whoami.exe":
            sid = "invalid" if problem == "identity" else "S-1-5-21-123-1001"
            return subprocess.CompletedProcess(command, 0, f'"account","{sid}"\r\n'.encode())
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(providers.subprocess, "run", run)
    with pytest.raises(OSError, match="restrict runtime key permissions"):
        providers.save_runtime_api_key("sk-test-1234567890abcdefghijklmnop")
    assert not list(tmp_path.iterdir())
