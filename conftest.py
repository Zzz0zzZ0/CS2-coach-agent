"""Tests are offline and cannot consume model quota or ingest production knowledge."""
import os
import socket
from contextvars import ContextVar
import pytest

os.environ.update({
    'PYTHON_DOTENV_DISABLED': '1', 'DASHSCOPE_API_KEY': '',
    'DASHSCOPE_KEY_FILE': '/nonexistent/cs2-test-key',
    'LLM_AUXILIARY_CALLS_ENABLED': 'false', 'AUTO_INGEST_ENABLED': 'false',
})

@pytest.fixture(autouse=True)
def deny_test_network(monkeypatch):
    pair_context = ContextVar('offline_socketpair', default=False)
    original_pair, original_connect = socket.socketpair, socket.socket.connect

    def local_pair(*args, **kwargs):
        token = pair_context.set(True)
        try:
            return original_pair(*args, **kwargs)
        finally:
            pair_context.reset(token)

    def denied(sock, address, *args, **kwargs):
        # Windows implements socketpair with loopback TCP; asyncio needs this private channel.
        if pair_context.get() and isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address, *args, **kwargs)
        pytest.fail('Network access is forbidden in offline tests; use an explicit fixture.')
    monkeypatch.setattr(socket, 'socketpair', local_pair)
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)


@pytest.fixture(autouse=True)
def isolated_analysis_history(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'ANALYSIS_RUN_DB', str(tmp_path / 'analysis_runs.sqlite'))
