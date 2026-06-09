import asyncio
import logging
from app.api.routers.scrapers import run_hltv_scraper_pipeline

logging.basicConfig(level=logging.INFO)

async def main():
    print("Triggering the pipeline with a hardcoded demo URL for full validation...")
    # Instead of fetching from HLTV which might not have demos for recent matches,
    # we directly trigger the downloader and pipeline.
    demo_url = "https://www.hltv.org/download/demo/108264"
    from app.scrapers.demo_downloader import download_and_extract_demo
    from app.services.tasks import parse_and_analyze_demo_task
    
    dem_files = await download_and_extract_demo(demo_url, "test_match_108264")
    for dem_path in dem_files:
        logging.info(f"Submitting {dem_path} for synchronous analysis...")
        parse_and_analyze_demo_task(dem_path, is_high_quality=True, auto_delete=True)

if __name__ == "__main__":
    asyncio.run(main())
