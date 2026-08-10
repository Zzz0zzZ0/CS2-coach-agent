"""Fetch recent professional CS2 demos from HLTV.

Examples:
    make fetch-demos ARGS="--days 7 --max-matches 10"
    make fetch-demos ARGS="--days 7 --download"
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.scrapers.demo_downloader import download_and_extract_demo, safe_match_name
from app.scrapers.hltv_scraper import fetch_high_quality_matches


def _manifest_path(match_id: str) -> Path:
    directory = Path(settings.DEMO_DOWNLOAD_DIR) / "manifests"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{match_id}.json"


def _write_manifest(match: dict, *, filters: dict, demo_files: list[str], status: str) -> Path:
    path = _manifest_path(match["match_id"])
    payload = {
        "source": "hltv",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "filters": filters,
        "status": status,
        "demo_files": demo_files,
        "match": match,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


async def run(args) -> list[dict]:
    filters = {"days": args.days, "min_rating": args.min_rating, "max_matches": args.max_matches}
    matches = await fetch_high_quality_matches(**filters)
    unique_matches = {match["match_id"]: match for match in matches}
    output = []

    for match in unique_matches.values():
        manifest_path = _manifest_path(match["match_id"])
        if args.download and manifest_path.exists() and not args.force:
            output.append({"match": match, "status": "skipped_existing_manifest"})
            continue

        demo_files = []
        status = "discovered"
        if args.download:
            match_name = "_".join(
                [match["event"], match["team1"], "vs", match["team2"], match["match_id"]]
            )
            demo_files = await download_and_extract_demo(
                match["demo_url"], safe_match_name(match_name)
            )
            status = "downloaded" if demo_files else "download_failed"
            manifest_path = _write_manifest(
                match, filters=filters, demo_files=demo_files, status=status
            )

        output.append(
            {
                "match": match,
                "status": status,
                "manifest": str(manifest_path),
                "demo_files": demo_files,
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch recent HLTV CS2 professional demos")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--min-rating", type=int, default=2, choices=range(6))
    parser.add_argument("--max-matches", type=int, default=10)
    parser.add_argument("--download", action="store_true", help="download and extract demos")
    parser.add_argument("--force", action="store_true", help="redownload matches with manifests")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
