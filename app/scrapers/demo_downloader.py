import os
import uuid
import shutil
import aiohttp
import asyncio
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
DOWNLOAD_DIR = Path("d:/newproject/data/demos")

async def download_and_extract_demo(demo_url: str, match_name: str) -> list[str]:
    """
    下载 rar 文件并使用 Bandizip (bz.exe) 解压出 .dem 文件。
    返回解压后的 .dem 文件绝对路径列表。
    """
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    rar_name = f"{match_name}_{uuid.uuid4().hex[:6]}.rar"
    rar_path = DOWNLOAD_DIR / rar_name
    extract_dir = DOWNLOAD_DIR / f"{match_name}_extract"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://www.hltv.org/"
    }
    
    logger.info(f"Downloading demo using DrissionPage from {demo_url} to {DOWNLOAD_DIR}...")
    
    # 1. 下载 RAR
    def _download_sync():
        from DrissionPage import ChromiumPage, ChromiumOptions
        co = ChromiumOptions()
        co.headless(False)
        co.set_argument('--window-position=-2000,-2000')
        co.set_paths(download_path=r"d:\newproject\data\demos")
        page = ChromiumPage(co)
        try:
            # 开启拦截下载
            mission = page.get(demo_url)
            # 等待下载开始并获取任务对象
            page.wait.download_begin()
            # 等待所有下载任务完成
            page.wait.all_downloads_done()
            # 由于可能下载的文件名是未知的（服务器返回），我们尝试从目录中找到最新的 rar，或者依赖重命名
            # 但是最简单的办法是抓取刚刚创建的 rar
            # 不过我们后续可以直接扫描 extract_dir，但原代码期望知道 rar_path
        except Exception as e:
            logger.error(f"Error downloading {demo_url} via DrissionPage: {e}")
        finally:
            page.quit()

    try:
        await asyncio.to_thread(_download_sync)
    except Exception as e:
        logger.error(f"Error executing download thread: {e}")
        return []
    
    # 因为 DrissionPage 接管下载后，文件名是服务器指定的（如 IEM-Chengdu-2024-xxx.rar）
    # 我们需要在 DOWNLOAD_DIR 中找到最新下载的 rar
    try:
        rars = list(DOWNLOAD_DIR.glob("*.rar"))
        if not rars:
            logger.error("No downloaded rar found.")
            return []
        rars.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        actual_rar_path = rars[0]
        # 重命名为我们期望的 rar_path
        if actual_rar_path != rar_path:
            actual_rar_path.rename(rar_path)
    except Exception as e:
        logger.error(f"Failed to locate or rename downloaded rar: {e}")
        return []

    logger.info(f"Download complete. Extracting {rar_path} to {extract_dir} using Bandizip...")
    
    # 2. 解压 (依赖系统中已安装并加到PATH的 Bandizip CLI: bz.exe)
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Bandizip 解压命令: bz.exe x -o:[dir] [archive]
        subprocess.run(["bz.exe", "x", f"-o:{str(extract_dir)}", str(rar_path)], check=True, capture_output=True)
        logger.info("Extraction successful.")
    except FileNotFoundError:
        logger.error("Bandizip (bz.exe) not found in PATH! Cannot extract.")
        # 回退清理压缩包
        if rar_path.exists():
            rar_path.unlink()
        return []
    except subprocess.CalledProcessError as e:
        logger.error(f"Extraction failed: {e.stderr.decode('utf-8', errors='ignore')}")
        return []
        
    # 3. 收集 .dem 文件
    dem_files = list(extract_dir.rglob("*.dem"))
    results = []
    
    for i, dem in enumerate(dem_files):
        new_name = DOWNLOAD_DIR / f"{match_name}_map{i+1}.dem"
        # 覆盖同名文件
        if new_name.exists():
            new_name.unlink()
        dem.rename(new_name)
        results.append(str(new_name.absolute()))
        logger.info(f"Extracted and prepared dem file: {new_name}")
        
    # 4. 清理残留包和解压目录
    try:
        rar_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")
        
    return results
