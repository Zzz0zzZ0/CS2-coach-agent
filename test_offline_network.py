"""Permit only the standard library's private socket pair; keep actual connections offline."""

import asyncio
import socket

import pytest


def test_private_socketpair_and_event_loop_still_work():
    first, second = socket.socketpair()
    try:
        first.sendall(b"x")
        assert second.recv(1) == b"x"
    finally:
        first.close(); second.close()
    assert asyncio.run(asyncio.sleep(0, result=7)) == 7


@pytest.mark.parametrize("host", ["127.0.0.1", "203.0.113.1"])
def test_ordinary_connections_remain_forbidden(host):
    with socket.socket() as connection:
        with pytest.raises(pytest.fail.Exception, match="Network access is forbidden"):
            connection.connect((host, 80))
        with pytest.raises(pytest.fail.Exception, match="Network access is forbidden"):
            connection.connect_ex((host, 80))
