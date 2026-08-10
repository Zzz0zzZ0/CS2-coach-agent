from datetime import date

from app.scrapers.demo_downloader import safe_match_name
from app.scrapers.hltv_scraper import (
    build_results_url,
    match_id_from_url,
    normalize_hltv_url,
    parse_result_card,
)


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
