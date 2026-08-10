"""Build the tactical knowledge base from parsed professional demos.

The seed is deliberately deterministic: it stores observed match evidence and
does not ask an LLM to invent tactical conclusions from a small sample.

Usage:
    make seed
    .venv/bin/python scripts/seed_knowledge.py --dry-run
"""
import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from pymilvus import DataType, Function, FunctionType, MilvusClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT))
from app.core.config import settings  # noqa: E402
from app.core.providers import get_embeddings  # noqa: E402
from app.services.parser_service import TacticalDemoParser  # noqa: E402

logger = logging.getLogger(__name__)
COLLECTION_NAME = "cs2_tactical_knowledge"
MAP_NAMES = {
    "de_ancient": "Ancient",
    "de_dust2": "Dust2",
    "de_inferno": "Inferno",
    "de_mirage": "Mirage",
    "de_nuke": "Nuke",
    "de_overpass": "Overpass",
    "de_vertigo": "Vertigo",
}


def _map_name(raw_name: str) -> str:
    return MAP_NAMES.get(raw_name, raw_name.removeprefix("de_").title())


def _match_id_from_path(path: Path) -> str:
    match = re.search(r"-(\d{5,})-", path.stem)
    return match.group(1) if match else path.stem


def _manifest_for(path: Path) -> dict:
    manifest_path = path.parent / "manifests" / f"{_match_id_from_path(path)}.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid demo manifest: %s", manifest_path)
        return {}


def _text(value, fallback: str = "Unknown") -> str:
    if value is None or str(value) in {"", "None", "nan"}:
        return fallback
    return str(value)


def _event_counts(rounds: list[dict]) -> dict[str, int]:
    counts = Counter()
    for round_data in rounds:
        counts["kills"] += len(round_data.get("kills", []))
        counts["grenades"] += len(round_data.get("grenades", []))
        counts["flash_blinds"] += len(round_data.get("flash_blinds", []))
        counts["plants"] += len(round_data.get("plants", []))
    return dict(counts)


def _metadata(
    *,
    map_name: str,
    match_id: str,
    tactic_type: str,
    round_number: str = "0",
    parent_id: str = "",
    context_level: str = "evidence",
    parent_content: str = "",
) -> dict[str, str]:
    return {
        "map": map_name,
        "side": "Both",
        "tactic_type": tactic_type,
        "source": f"hltv_demo:{match_id}",
        "match_id": match_id,
        "round_number": round_number,
        "parent_id": parent_id,
        "context_level": context_level,
        "parent_content": parent_content,
    }


def _round_content(map_name: str, round_data: dict) -> str:
    round_number = _text(round_data.get("round_number"), "?")
    winner = _text(round_data.get("winner"))
    reason = _text(round_data.get("reason"))
    kills = round_data.get("kills", [])
    grenades = round_data.get("grenades", [])
    blinds = round_data.get("flash_blinds", [])
    plants = round_data.get("plants", [])

    kill_lines = []
    for kill in kills:
        killer = _text(kill.get("killer"))
        victim = _text(kill.get("victim"))
        weapon = _text(kill.get("weapon"))
        first = " [first kill]" if kill.get("is_first_kill") else ""
        kill_lines.append(f"{killer} killed {victim} with {weapon}{first}")

    grenade_counts = Counter(_text(grenade.get("type")) for grenade in grenades)
    grenade_text = ", ".join(f"{kind}: {count}" for kind, count in sorted(grenade_counts.items()))
    plant_text = ", ".join(
        f"{_text(plant.get('planter'))} at {_text(plant.get('site'))}" for plant in plants
    )

    sections = [
        f"[Professional Demo Evidence | {map_name} | Round {round_number}]",
        f"Round winner: {winner}. End reason: {reason}.",
        f"Kills ({len(kills)}): " + ("; ".join(kill_lines) if kill_lines else "none recorded."),
        f"Grenades ({len(grenades)}): " + (grenade_text or "none recorded."),
        f"Flash blinds: {len(blinds)}.",
        f"Bomb plants ({len(plants)}): " + (plant_text or "none recorded."),
        "This entry records parsed events only; it does not assert a causal tactical conclusion.",
    ]
    return " ".join(sections)


def _build_documents(demo_dir: Path) -> list[Document]:
    documents: list[Document] = []
    demo_paths = sorted(demo_dir.glob("*.dem"))
    if not demo_paths:
        raise FileNotFoundError(f"No .dem files found in {demo_dir}")

    for demo_path in demo_paths:
        parsed = TacticalDemoParser(str(demo_path)).parse_to_dict()
        rounds = parsed.get("rounds", []) if parsed else []
        if not rounds:
            logger.warning("Skipping demo without parsed rounds: %s", demo_path)
            continue

        map_name = _map_name(_text(parsed.get("map_name"), "Unknown"))
        match_id = _match_id_from_path(demo_path)
        manifest = _manifest_for(demo_path)
        match = manifest.get("match", {})
        teams = f"{_text(match.get('team1'))} vs {_text(match.get('team2'))}"
        event = _text(match.get("event"))
        counts = _event_counts(rounds)
        winners = Counter(_text(item.get("winner")) for item in rounds)
        first_kills = [
            kill
            for item in rounds
            for kill in item.get("kills", [])
            if kill.get("is_first_kill")
        ]
        first_kill_weapons = Counter(_text(kill.get("weapon")) for kill in first_kills)
        first_kill_players = Counter(_text(kill.get("killer")) for kill in first_kills)

        base = (
            f"[Professional Demo Summary | {map_name}] Match {teams}, event {event}, "
            f"HLTV match id {match_id}. Source file: {demo_path.name}. "
        )
        summary = (
            base
            + f"Parsed {len(rounds)} rounds, {counts.get('kills', 0)} kills, "
            + f"{len(first_kills)} first kills, {counts.get('grenades', 0)} grenades, "
            + f"{counts.get('flash_blinds', 0)} flash-blind events, and {counts.get('plants', 0)} bomb plants. "
            + "Round winners: "
            + ", ".join(f"{side} {count}" for side, count in sorted(winners.items()))
            + ". This is a factual event summary from a professional demo; tactical causality requires coach review."
        )
        parent_id = f"{match_id}:{map_name}:summary"
        documents.append(
            Document(
                page_content=summary,
                metadata=_metadata(
                    map_name=map_name,
                    match_id=match_id,
                    tactic_type="Professional Match Summary",
                    parent_id=parent_id,
                    context_level="parent",
                    parent_content=summary,
                ),
            )
        )

        opening = (
            base
            + f"Opening-duel evidence: {len(first_kills)} first kills. "
            + "Weapons: "
            + (", ".join(f"{weapon} {count}" for weapon, count in first_kill_weapons.most_common()) or "none")
            + ". First-kill players: "
            + (", ".join(f"{player} {count}" for player, count in first_kill_players.most_common()) or "none")
            + ". Individual round evidence is stored separately."
        )
        documents.append(
            Document(
                page_content=opening,
                metadata=_metadata(
                    map_name=map_name,
                    match_id=match_id,
                    tactic_type="Opening Duel Evidence",
                    parent_id=parent_id,
                    parent_content=summary,
                ),
            )
        )

        for round_data in rounds:
            round_number = _text(round_data.get("round_number"), "0")
            documents.append(
                Document(
                    page_content=_round_content(map_name, round_data),
                    metadata=_metadata(
                        map_name=map_name,
                        match_id=match_id,
                        tactic_type="Round Event Evidence",
                        round_number=round_number,
                        parent_id=parent_id,
                        parent_content=summary,
                    ),
                )
            )

    return documents


def seed_milvus_db(documents: list[Document], *, append: bool = False) -> None:
    milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
    milvus_token = os.getenv("MILVUS_TOKEN", "")
    embeddings = get_embeddings()
    print(
        f"=== [职业 Demo 战术知识库初始化] Milvus @ {milvus_uri} | "
        f"documents={len(documents)} | replace={not append} ==="
    )
    client = MilvusClient(uri=milvus_uri, token=milvus_token)
    if append and client.has_collection(COLLECTION_NAME):
        fields = client.describe_collection(COLLECTION_NAME).get("fields", [])
        field_names = {field.get("name") for field in fields}
        if "sparse" not in field_names:
            raise RuntimeError("现有集合不支持 BM25，请先用默认的 make seed 重建，不能对旧 dense 集合 append。")
    elif client.has_collection(COLLECTION_NAME):
        client.drop_collection(COLLECTION_NAME)

    vectors = embeddings.embed_documents([document.page_content for document in documents])
    if not append or not client.has_collection(COLLECTION_NAME):
        schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field(field_name="pk", datatype=DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field(field_name="map", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="side", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="tactic_type", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="match_id", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="round_number", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="parent_id", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="context_level", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="parent_content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(
            field_name="text",
            datatype=DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
        )
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=len(vectors[0]))
        schema.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="text_bm25_emb",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
        )
        client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )

    rows = []
    for document, vector in zip(documents, vectors):
        rows.append(
            {
                **document.metadata,
                "text": document.page_content,
                "vector": vector,
            }
        )
    client.insert(COLLECTION_NAME, rows)
    client.flush(COLLECTION_NAME)
    client.load_collection(COLLECTION_NAME)
    print(f"✅ 已写入 {len(documents)} 条结构化 Demo 证据到 '{COLLECTION_NAME}'。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Milvus from parsed professional CS2 demos")
    parser.add_argument("--demo-dir", type=Path, default=Path(settings.DEMO_DOWNLOAD_DIR))
    parser.add_argument("--dry-run", action="store_true", help="parse and count documents without writing Milvus")
    parser.add_argument("--append", action="store_true", help="append instead of replacing the collection")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    documents = _build_documents(args.demo_dir)
    counts = Counter(document.metadata["tactic_type"] for document in documents)
    print(f"发现 {len(documents)} 条文档: {dict(counts)}")
    if args.dry_run:
        return
    seed_milvus_db(documents, append=args.append)


if __name__ == "__main__":
    main()
