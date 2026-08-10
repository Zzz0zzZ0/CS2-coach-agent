import asyncio
import logging
import re
from datetime import date, timedelta
from urllib.parse import urlencode

logger = logging.getLogger(__name__)
HLTV_BASE_URL = "https://www.hltv.org"


def build_results_url(days: int = 3, min_rating: int = 2, today: date | None = None) -> str:
    """Build a bounded HLTV query for recent completed matches with demos."""
    if days < 1:
        raise ValueError("days must be at least 1")
    if min_rating < 0 or min_rating > 5:
        raise ValueError("min_rating must be between 0 and 5")

    end_date = today or date.today()
    start_date = end_date - timedelta(days=days)
    params = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "content": "demo",
        "stars": str(min_rating),
        "offset": "0",
    }
    return f"{HLTV_BASE_URL}/results?{urlencode(params)}"


def normalize_hltv_url(value: str | None) -> str | None:
    if not value:
        return None
    return value if value.startswith("http") else f"{HLTV_BASE_URL}{value}"


def match_id_from_url(match_url: str | None) -> str | None:
    if not match_url:
        return None
    match = re.search(r"/matches/(\d+)(?:/|$)", match_url)
    return match.group(1) if match else None


def extract_demo_path(tab) -> str | None:
    """Extract the first official HLTV demo link from a match page."""
    html = tab.html
    match = re.search(r'data-demo-link=["\']([^"\']+)', html)
    if match:
        return match.group(1)
    for link in tab.eles('xpath://a[@data-demo-link]'):
        demo_path = link.attr("data-demo-link")
        if demo_path:
            return demo_path
    return None


def parse_result_card(html: str) -> dict | None:
    """Parse stable text from an HLTV result card without depending on DOM objects."""
    href = re.search(r'href=["\']([^"\']*/matches/\d+[^"\']*)', html)
    team1 = re.search(
        r'class=["\'][^"\']*\bteam1\b[^"\']*["\'][\s\S]*?'
        r'class=["\']team[^"\']*["\']>\s*([^<]+?)\s*</div>',
        html,
    )
    team2 = re.search(
        r'class=["\'][^"\']*\bteam2\b[^"\']*["\'][\s\S]*?'
        r'class=["\']team[^"\']*["\']>\s*([^<]+?)\s*</div>',
        html,
    )
    event = re.search(r'class=["\']event-name["\']>\s*([^<]+?)\s*</', html)
    if not href or not match_id_from_url(href.group(1)):
        return None
    return {
        "match_id": match_id_from_url(href.group(1)),
        "match_url": normalize_hltv_url(href.group(1)),
        "team1": team1.group(1).strip() if team1 else "T1",
        "team2": team2.group(1).strip() if team2 else "T2",
        "event": event.group(1).strip() if event else "Unknown Event",
    }


def _fetch_matches_sync(days=3, min_rating=2, max_matches=10):
    from DrissionPage import ChromiumPage, ChromiumOptions

    logger.info(
        "Fetching recent HLTV demos: days=%s, min_rating=%s, max_matches=%s",
        days,
        min_rating,
        max_matches,
    )
    matches_with_demo = []
    page = None

    co = ChromiumOptions()
    co.headless(False)
    co.set_argument("--window-position=-2000,-2000")

    try:
        page = ChromiumPage(co)
        results = []
        windows = [days]
        if days < 30:
            windows.append(30)

        for window_days in windows:
            page.get(build_results_url(days=window_days, min_rating=min_rating))
            page.wait.ele_displayed(".result-con", timeout=10)
            results = page.eles(".result-con")
            if results:
                if window_days != days:
                    logger.info("No demos in %s days; widened search window to %s days", days, window_days)
                break
            html = page.html
            body_text = page.ele("tag:body").text if page.ele("tag:body") else ""
            if "cf-chl" in html or "Just a moment" in html:
                logger.error("HLTV Cloudflare challenge blocked the results page")
                return []
            if "No results" in body_text:
                logger.info("No demos found in %s-day window", window_days)
                continue
            logger.error("HLTV results page was unavailable. Page title: %s", page.title)
            return []

        for result in results:
            if len(matches_with_demo) >= max_matches:
                break
            try:
                card = parse_result_card(result.html)
                if not card:
                    continue
                match_id = card["match_id"]
                team1 = card["team1"]
                team2 = card["team2"]
                event = card["event"]
                match_url = card["match_url"]
                demo_url = None

                tab = page.new_tab(match_url)
                try:
                    if tab.wait.ele_displayed('xpath://a[@data-demo-link]', timeout=5):
                        demo_url = normalize_hltv_url(extract_demo_path(tab))
                finally:
                    tab.close()

                if not demo_url:
                    continue

                matches_with_demo.append(
                    {
                        "match_id": match_id,
                        "team1": team1,
                        "team2": team2,
                        "event": event,
                        "match_url": match_url,
                        "demo_url": demo_url,
                    }
                )
                logger.info("Found demo: %s vs %s [%s]", team1, team2, event)
            except Exception:
                logger.exception("Failed to parse one HLTV result")
    except Exception:
        logger.exception("HLTV scraper failed")
    finally:
        if page is not None:
            page.quit()

    return matches_with_demo


async def fetch_high_quality_matches(days=3, min_rating=2, max_matches=10):
    """Fetch recent completed professional matches whose demo is available."""
    return await asyncio.to_thread(_fetch_matches_sync, days, min_rating, max_matches)
