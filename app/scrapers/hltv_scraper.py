import asyncio
import logging
from DrissionPage import ChromiumPage, ChromiumOptions
import time

logger = logging.getLogger(__name__)

def _fetch_matches_sync(days=3, min_rating=1, max_matches=5):
    logger.info(f"Start fetching HLTV matches using DrissionPage (headless)... days={days}, min_rating={min_rating}, max={max_matches}")
    matches_with_demo = []
    
    co = ChromiumOptions()
    co.headless(False)
    co.set_argument('--window-position=-2000,-2000') # 采用半无头模式，将窗口移动到屏幕外避免打扰
    
    page = ChromiumPage(co)
    try:
        # 组装带星级的查询参数
        # 比如 rating 1 对应 1 星以上, hltv 对应参数是 stars=1
        url = f"https://www.hltv.org/results?stars={min_rating}"
        page.get(url)
        
        # 检查是否遇到 Cloudflare 盾
        if page.wait.ele_displayed('.result-con', timeout=10):
            logger.info("Successfully bypassed or no CF encountered.")
            results = page.eles('.result-con')
            
            # 限制获取数量
            results = results[:max_matches]
            
            for res in results:
                try:
                    a_tag = res.ele('tag:a')
                    if not a_tag:
                        continue
                        
                    match_url = a_tag.link
                    match_id = match_url.split('/')[4] # /matches/12345/team1-vs-team2
                    
                    team1_ele = res.ele('.team1 .team')
                    team2_ele = res.ele('.team2 .team')
                    team1 = team1_ele.text if team1_ele else "T1"
                    team2 = team2_ele.text if team2_ele else "T2"
                    
                    event_ele = res.ele('.event-name')
                    event = event_ele.text.replace(" ", "_").replace("/", "") if event_ele else "Event"
                    
                    demo_url = None
                    try:
                        # 进入比赛详情页获取 demo 下载链接
                        match_page_url = "https://www.hltv.org" + match_url if match_url.startswith("/") else match_url
                        
                        # 在后台新建一个标签页或直接当前页导航，为了不破坏外层循环，我们复用 page 但每次记得后退？
                        # DrissionPage 允许新建标签页
                        tab = page.new_tab(match_page_url)
                        if tab.wait.ele_displayed('xpath://a[@data-demo-link]', timeout=5):
                            demo_path = tab.ele('xpath://a[@data-demo-link]').attr('data-demo-link')
                            if demo_path:
                                demo_url = "https://www.hltv.org" + demo_path
                        tab.close()
                    except Exception as demo_err:
                        logger.warning(f"Failed to fetch demo url for {match_id}: {demo_err}")

                    matches_with_demo.append({
                        "match_id": match_id,
                        "team1": team1,
                        "team2": team2,
                        "event": event,
                        "match_url": match_url,
                        "demo_url": demo_url
                    })
                    logger.info(f"Scraped match: {team1} vs {team2} [{event}] | Demo: {demo_url}")
                except Exception as inner_e:
                    logger.warning(f"Error parsing a match result: {inner_e}")
                    
        else:
            logger.error("Failed to bypass Cloudflare in headless mode. Page title: " + page.title)
            # 保存用于后续分析
            with open("error_dp.html", "w", encoding="utf-8") as f:
                f.write(page.html)
                
    except Exception as e:
        logger.error(f"DrissionPage Scraper failed: {e}")
    finally:
        page.quit()
        
    return matches_with_demo

async def fetch_high_quality_matches(days=3, min_rating=1, max_matches=5):
    """
    使用 DrissionPage 无头浏览器获取最近的高质量比赛，对抗 Cloudflare 反爬。
    """
    # 因为 DrissionPage 是同步库，使用 asyncio.to_thread 防止阻塞事件循环
    return await asyncio.to_thread(_fetch_matches_sync, days, min_rating, max_matches)
