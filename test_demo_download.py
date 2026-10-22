import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.scrapers import demo_downloader


def test_browser_download_does_not_retry_navigation(tmp_path, monkeypatch):
    page = MagicMock()
    page.get.side_effect = lambda *a, **kw: (tmp_path / "official.rar").write_bytes(b"archive fixture")
    monkeypatch.setitem(sys.modules, "DrissionPage", SimpleNamespace(
        ChromiumPage=MagicMock(return_value=page), ChromiumOptions=MagicMock()))
    monkeypatch.setattr(demo_downloader, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(demo_downloader.time, "sleep", lambda _: None)
    async def immediate(function):
        return function()
    monkeypatch.setattr(demo_downloader.asyncio, "to_thread", immediate)

    def extract(archive, directory):
        directory.mkdir()
        (directory / "map.dem").write_bytes(b"synthetic fixture, not a real demo")
        return True

    monkeypatch.setattr(demo_downloader, "_extract_archive", extract)
    # The fake thread completes inline, avoiding Windows event-loop sockets in this offline test.
    with pytest.raises(StopIteration) as completed:
        demo_downloader.download_and_extract_demo("https://example.test/demo", "one_series").send(None)
    result = completed.value.value
    page.get.assert_called_once_with("https://example.test/demo", retry=0)
    page.quit.assert_called_once()
    assert len(result) == 1
    assert (tmp_path / "one_series_map1.dem").read_bytes() == b"synthetic fixture, not a real demo"
