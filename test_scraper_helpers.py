from argparse import Namespace
import asyncio
from datetime import date
import json

from app.scrapers.demo_downloader import safe_match_name
from app.scrapers.hltv_scraper import (
    build_results_url,
    match_id_from_url,
    normalize_hltv_url,
    parse_result_card,
)
from scripts.fetch_recent_demos import _manifest_complete, run


def test_results_url_is_bounded_to_recent_demo_matches():
    url = build_results_url(days=7, min_rating=2, today=date(2026, 8, 10))

    assert "startDate=2026-08-03" in url
    assert "endDate=2026-08-10" in url
    assert "content=demo" in url
    assert "stars=2" in url
    assert "offset=0" in url


def test_hltv_url_helpers():
    relative = "/matches/12345/team-a-vs-team-b"

    assert match_id_from_url(relative) == "12345"
    assert normalize_hltv_url(relative) == "https://www.hltv.org" + relative
    assert match_id_from_url("/results") is None


def test_match_name_is_safe_for_a_filename():
    value = safe_match_name("IEM / Chengdu: Team A vs Team B / 123")

    assert value == "IEM_Chengdu_Team_A_vs_Team_B_123"


def test_parse_current_hltv_result_card():
    html = """
    <div class="result-con">
      <a href="/matches/12345/team-a-vs-team-b" class="a-reset">
        <div class="line-align team1"><div class="team team-won">Team A</div></div>
        <div class="line-align team2"><div class="team">Team B</div></div>
        <span class="event-name">Example LAN</span>
      </a>
    </div>
    """

    assert parse_result_card(html) == {
        "match_id": "12345",
        "match_url": "https://www.hltv.org/matches/12345/team-a-vs-team-b",
        "team1": "Team A",
        "team2": "Team B",
        "event": "Example LAN",
    }


def test_fetch_script_accepts_reviewed_selection(tmp_path):
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"matches": [{
        "match_id": "12345",
        "team1": "Spirit",
        "team2": "Falcons",
        "event": "Example LAN",
        "match_url": "https://www.hltv.org/matches/12345/example",
        "demo_url": "https://www.hltv.org/download/demo/999",
    }]}), encoding="utf-8")

    result = asyncio.run(run(Namespace(
        days=7, min_rating=2, max_matches=10,
        download=False, force=False, selection_file=selection,
    )))

    assert result[0]["match"]["match_id"] == "12345"
    assert result[0]["status"] == "discovered"


def test_only_complete_download_manifests_are_skipped(tmp_path):
    demo = tmp_path / "map1.dem"
    demo.write_bytes(b"demo")
    manifest = tmp_path / "match.json"

    manifest.write_text(json.dumps({
        "status": "downloaded", "demo_files": [str(demo)],
    }), encoding="utf-8")
    assert _manifest_complete(manifest) is True

    manifest.write_text(json.dumps({
        "status": "download_failed", "demo_files": [],
    }), encoding="utf-8")
    assert _manifest_complete(manifest) is False
