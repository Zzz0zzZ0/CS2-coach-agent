"""Tests are offline and cannot consume model quota or ingest production knowledge."""
import os
import socket
import pytest

os.environ.update({
    'PYTHON_DOTENV_DISABLED': '1', 'DASHSCOPE_API_KEY': '',
    'DASHSCOPE_KEY_FILE': '/nonexistent/cs2-test-key',
    'LLM_AUXILIARY_CALLS_ENABLED': 'false', 'AUTO_INGEST_ENABLED': 'false',
})

@pytest.fixture(autouse=True)
def deny_test_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('Network access is forbidden in offline tests; use an explicit fixture.')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
