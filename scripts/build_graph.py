"""Build the local GraphRAG sidecar from professional demo files."""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.graph_rag_service import GraphRAGClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local CS2 GraphRAG sidecar")
    parser.add_argument("--demo-dir", type=Path, default=Path(settings.DEMO_DOWNLOAD_DIR))
    parser.add_argument("--db-path", type=Path, default=Path(settings.GRAPH_DB_PATH))
    args = parser.parse_args()
    client = GraphRAGClient(args.db_path)
    result = client.build_from_demo_dir(args.demo_dir)
    print(f"GraphRAG built: {result}")


if __name__ == "__main__":
    main()
