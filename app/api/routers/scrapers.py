from fastapi import APIRouter, BackgroundTasks
import logging
from app.scrapers.hltv_scraper import fetch_high_quality_matches
from app.scrapers.demo_downloader import download_and_extract_demo
from app.services.tasks import parse_and_analyze_demo_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scrapers", tags=["scrapers"])

async def run_hltv_scraper_pipeline():
    logger.info("Starting manual HLTV scraping pipeline...")
    matches = await fetch_high_quality_matches(days=3, min_rating=1, max_matches=1)
    if not matches:
        logger.info("No matches found or Cloudflare blocked.")
        return
        
    for match in matches:
        demo_url = match.get("demo_url")
        if demo_url:
            match_name = f"{match['event']}_{match['team1']}_vs_{match['team2']}_{match['match_id']}"
            logger.info(f"Downloading demo for {match_name}...")
            
            dem_files = await download_and_extract_demo(demo_url, match_name)
            for dem_path in dem_files:
                logger.info(f"Submitting {dem_path} for synchronous analysis...")
                # 触发现有的流水线，为了测试改为同步执行
                parse_and_analyze_demo_task(dem_path, is_high_quality=True, auto_delete=True)
                
    logger.info("HLTV scraping pipeline completed.")

@router.post("/hltv/trigger")
async def trigger_hltv_scraper(background_tasks: BackgroundTasks):
    """
    手动触发 HLTV S级赛事爬虫流水线 (异步执行)
    """
    background_tasks.add_task(run_hltv_scraper_pipeline)
    return {"status": "accepted", "message": "HLTV scraper pipeline triggered in background"}
