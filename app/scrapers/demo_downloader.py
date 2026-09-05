import asyncio
import logging
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)
DOWNLOAD_DIR = Path(settings.DEMO_DOWNLOAD_DIR)


def safe_match_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value[:160] or f"match_{uuid.uuid4().hex[:8]}"


def _extract_archive(archive_path: Path, extract_dir: Path) -> bool:
    """Use an installed native archive tool; keep the archive if none works."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        ["unar", "-o", str(extract_dir), str(archive_path)],
        ["7z", "x", "-y", f"-o{extract_dir}", str(archive_path)],
        ["7zz", "x", "-y", f"-o{extract_dir}", str(archive_path)],
        ["unrar", "x", "-o+", str(archive_path), str(extract_dir)],
        ["bsdtar", "-xf", str(archive_path), "-C", str(extract_dir)],
        ["bz.exe", "x", f"-o:{extract_dir}", str(archive_path)],
    ]
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError as error:
            logger.warning("Archive extractor %s failed: %s", command[0], error.stderr.decode(errors="ignore"))
    return False


async def download_and_extract_demo(demo_url: str, match_name: str) -> list[str]:
    """Download a HLTV archive and return extracted .dem paths."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = safe_match_name(match_name)
    archive_path = DOWNLOAD_DIR / f"{safe_name}_{uuid.uuid4().hex[:6]}.rar"
    extract_dir = DOWNLOAD_DIR / f"{safe_name}_extract"

    logger.info("Downloading demo from %s to %s", demo_url, DOWNLOAD_DIR)

    before_files = {
        path.resolve() for path in DOWNLOAD_DIR.iterdir() if path.is_file()
    }
    before_archives = {path.resolve() for path in DOWNLOAD_DIR.glob("*.rar")}

    def _download_sync():
        from DrissionPage import ChromiumPage, ChromiumOptions

        co = ChromiumOptions()
        co.auto_port()
        co.headless(False)
        co.set_argument("--window-position=-2000,-2000")
        co.set_paths(download_path=str(DOWNLOAD_DIR.absolute()))
        page = ChromiumPage(co)
        page.set.download_path(str(DOWNLOAD_DIR.absolute()))
        try:
            page.get(demo_url)
            deadline = time.time() + 300
            last_size = -1
            stable_checks = 0
            while time.time() < deadline:
                archives = [
                    path
                    for path in DOWNLOAD_DIR.glob("*.rar")
                    if path.resolve() not in before_archives
                ]
                if archives:
                    current_size = max(path.stat().st_size for path in archives)
                    if current_size == last_size and current_size > 0:
                        stable_checks += 1
                        if stable_checks >= 3:
                            return
                    else:
                        stable_checks = 0
                        last_size = current_size
                time.sleep(2)
            raise TimeoutError("Timed out waiting for the new HLTV archive")
        finally:
            page.quit()

    try:
        await asyncio.to_thread(_download_sync)
    except Exception:
        logger.exception("Failed to download demo archive")
        return []

    new_archives = [
        path for path in DOWNLOAD_DIR.glob("*.rar") if path.resolve() not in before_archives
    ]
    if not new_archives:
        logger.error("HLTV download completed without a new .rar archive")
        return []
    actual_archive = max(new_archives, key=lambda path: path.stat().st_mtime)
    actual_archive.rename(archive_path)

    for path in DOWNLOAD_DIR.iterdir():
        if not path.is_file() or path.resolve() in before_files or path == archive_path:
            continue
        try:
            path.unlink()
            logger.info("Removed temporary download artifact: %s", path.name)
        except OSError:
            logger.warning("Could not remove temporary download artifact: %s", path)

    if not _extract_archive(archive_path, extract_dir):
        logger.error("No working archive extractor found; archive retained at %s", archive_path)
        return []

    dem_files = sorted(extract_dir.rglob("*.dem"))
    results = []
    for index, dem in enumerate(dem_files, start=1):
        target = DOWNLOAD_DIR / f"{safe_name}_map{index}.dem"
        if target.exists():
            target.unlink()
        dem.rename(target)
        results.append(str(target.absolute()))
        logger.info("Extracted demo: %s", target)

    archive_path.unlink(missing_ok=True)
    shutil.rmtree(extract_dir, ignore_errors=True)
    return results
