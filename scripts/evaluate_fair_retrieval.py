"""Isolated, same-corpus retrieval ablation; unreviewed qrels never produce quality scores."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import sqlite3
import statistics
import time


MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RELATIONS = {"KILL": "kill", "USES_UTILITY": "grenade", "FLASH_BLIND": "flash", "PLANTS_BOMB": "plant"}
METHODS = ("bm25", "dense", "dense_bm25_rrf", "sql_reference", "graph_path_reference")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Freeze artifacts: choose a new path for every changed experiment.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def review_packet(corpus, queries):
    docs = [json.loads(line) for line in corpus.read_text().splitlines() if line.strip()]
    dataset = json.loads(queries.read_text())
    validate_inputs(docs, dataset)
    return {"version": "fair-qrels-review-v1", "corpus_sha256": digest(corpus), "queries_sha256": digest(queries),
            "instructions": "Independently review all metadata-eligible rounds using frozen source events, without viewing rankings. Entities mean roster participation. Record all relevant rounds and supporting event IDs; blank labels are unjudged, not negatives. Approval is a review assertion, not a software guarantee of independence.",
            "judgments": [{"query_id": q["id"], "status": "pending_review", "reviewer": None, "reviewed_at": None,
                           "exhaustive": False, "scope_basis": None, "relevance": []} for q in dataset["cases"]]}


def export_corpus(graph_db, output):
    """Export raw observable facts, with no production retrieval/scoring imports."""
    with sqlite3.connect(Path(graph_db).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        rounds = db.execute("SELECT * FROM nodes WHERE node_type='round' ORDER BY node_id").fetchall()
        events = defaultdict(list)
        for row in db.execute("SELECT * FROM nodes WHERE node_type='event' ORDER BY node_id"):
            events[(row["match_id"], row["map_name"], row["round_number"])].append(row)
        links = defaultdict(list)
        for row in db.execute("SELECT source_id,relation,target_id FROM edges ORDER BY source_id,relation,target_id"):
            if row["relation"] in RELATIONS:
                links[row["source_id"]].append([row["relation"], row["target_id"]])
        docs = []
        for row in rounds:
            props = json.loads(row["properties"])
            roster = props.get("participants", [])
            if not props.get("participants_complete"):
                raise ValueError(f"Incomplete roster: {row['node_id']}")
            facts = []
            for item in events[(row["match_id"], row["map_name"], row["round_number"])]:
                p = json.loads(item["properties"])
                # Keep all fields in the frozen source packet; the common retrieval
                # representation below intentionally describes only these facts.
                facts.append({"id": item["node_id"], "kind": p["kind"], "properties": p})
            lines = [f"Match {row['match_id']} map {row['map_name']} round {row['round_number']}. Winner {props.get('winner')}. Reason {props.get('reason')}."]
            lines.extend(f"Participant {p['name']} team {p['team']} side {p['side']}." for p in sorted(roster, key=lambda p: p["steamid"]))
            counts = Counter()
            for event in facts:
                p, kind = event["properties"], event["kind"]
                if kind == "kill":
                    text = f"{p.get('killer')} kills {p.get('victim')} weapon {p.get('weapon')}"
                    if p.get("is_first_kill"):
                        text += " opening first kill"
                elif kind == "plant":
                    text = f"{p.get('planter')} bomb plant site {p.get('site')}"
                elif kind == "grenade":
                    text = f"{p.get('thrower')} grenade {p.get('grenade_type', p.get('type', 'utility'))}"
                else:
                    # Ambiguous attribution remains explicit in the source packet.
                    text = f"{p.get('victim')} flash blinded"
                counts[text] += 1
            lines.extend(f"{text} count {count}." for text, count in sorted(counts.items()))
            docs.append({"id": row["node_id"], "match_id": row["match_id"], "map": row["map_name"],
                         "round": int(row["round_number"]), "text": "\n".join(lines),
                         "entities": sorted({str(p[k]).casefold() for p in roster for k in ("name", "team", "steamid")}),
                         "events": facts, "links": links[row["node_id"]]})
    with Path(output).open("x", encoding="utf-8") as stream:
        for doc in docs:
            stream.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
    return {"rounds": len(docs), "matches": sorted({d["match_id"] for d in docs}), "sha256": digest(output)}


def validate_inputs(docs, dataset):
    ids = [d["id"] for d in docs]
    cases = dataset["cases"]
    if not ids or len(ids) != len(set(ids)) or not cases:
        raise ValueError("Corpus and queries must be nonempty, with unique IDs")
    if len({q["id"] for q in cases}) != len(cases):
        raise ValueError("Duplicate query ID")
    for q in cases:
        if not q["query"].strip() or set(q.get("filters", {})) - {"map", "match_id", "round"}:
            raise ValueError(f"Invalid query or filters: {q['id']}")
        if q.get("event_kind") not in RELATIONS.values():
            raise ValueError(f"Invalid structured event kind: {q['id']}")
    for d in docs:
        event_kinds = {e["id"]: e["kind"] for e in d["events"]}
        if len(event_kinds) != len(d["events"]):
            raise ValueError("Duplicate event ID")
        linked = {target: RELATIONS[relation] for relation, target in d["links"]}
        if linked != event_kinds or len(d["links"]) != len(linked):
            raise ValueError(f"Event/path evidence mismatch: {d['id']}")


def reviewed_qrels(packet, docs, dataset, corpus_hash, query_hash):
    if packet is None:
        return None
    if packet.get("corpus_sha256") != corpus_hash or packet.get("queries_sha256") != query_hash:
        raise ValueError("Qrels frozen hashes do not match corpus/queries")
    items = packet["judgments"]
    cases = {q["id"] for q in dataset["cases"]}
    if len(items) != len(cases) or {j["query_id"] for j in items} != cases:
        raise ValueError("Qrels must cover each query exactly once")
    known = {d["id"] for d in docs}
    approved = True
    result = {}
    for item in items:
        rows = item["relevance"]
        if len({r["source_round_id"] for r in rows}) != len(rows):
            raise ValueError("Duplicate qrel")
        for r in rows:
            if r["source_round_id"] not in known or type(r["grade"]) is not int or r["grade"] not in range(4) or not r.get("basis"):
                raise ValueError("Invalid qrel source, grade or basis")
        approved &= (item.get("status") == "approved" and item.get("exhaustive") is True
                     and bool(item.get("reviewer")) and bool(item.get("reviewed_at"))
                     and bool(item.get("scope_basis")))
        result[item["query_id"]] = {r["source_round_id"]: r["grade"] for r in rows if r["grade"] > 0}
    return result if approved else None


def metrics(ranked, relevant, k=5):
    if len(ranked) != len(set(ranked)):
        raise ValueError("Duplicate returned source IDs")
    hits = ranked[:k]
    if not relevant:
        return {"recall_at_k": None, "ndcg_at_k": None, "false_retrieval": bool(hits), "false_abstention": None}
    dcg = sum((2 ** relevant.get(doc, 0) - 1) / math.log2(i + 2) for i, doc in enumerate(hits))
    ideal = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(sorted(relevant.values(), reverse=True)[:k]))
    return {"recall_at_k": len(set(hits) & relevant.keys()) / len(relevant), "ndcg_at_k": dcg / ideal,
            "false_retrieval": None, "false_abstention": not bool(hits)}


def eligible(doc, case, entity_constraint):
    return (all(doc.get(k) == v for k, v in case.get("filters", {}).items())
            and (not entity_constraint or all(e.casefold() in doc["entities"] for e in case.get("entities", []))))


def build_index(docs):
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE VIRTUAL TABLE texts USING fts5(text, tokenize='unicode61');
        CREATE TABLE facts (doc INTEGER, kind TEXT);
        CREATE TABLE paths (doc INTEGER, relation TEXT, event TEXT);
        CREATE TABLE events (id TEXT PRIMARY KEY, kind TEXT);
        CREATE INDEX fact_kind ON facts(kind,doc);
        CREATE INDEX path_doc ON paths(doc);
        CREATE TEMP TABLE allowed (doc INTEGER PRIMARY KEY);
    """)
    for i, doc in enumerate(docs):
        db.execute("INSERT INTO texts(rowid,text) VALUES (?,?)", (i, doc["text"]))
        db.executemany("INSERT INTO facts VALUES (?,?)", [(i, e["kind"]) for e in doc["events"]])
        db.executemany("INSERT INTO events VALUES (?,?)", [(e["id"], e["kind"]) for e in doc["events"]])
        db.executemany("INSERT INTO paths VALUES (?,?,?)", [(i, rel, target) for rel, target in doc["links"]])
    return db


def ranks(db, docs, case, constraint, query_vector, vectors, k):
    started = time.perf_counter()
    durations = {}
    allowed = [i for i, doc in enumerate(docs) if eligible(doc, case, constraint)]
    db.execute("DELETE FROM allowed")
    db.executemany("INSERT INTO allowed VALUES (?)", [(i,) for i in allowed])
    preparation_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    tokens = re.findall(r"[^\W_]+", case["query"].casefold())
    expression = " OR ".join('"' + token + '"' for token in tokens)
    bm25 = [r[0] for r in db.execute("SELECT rowid FROM texts WHERE texts MATCH ? AND rowid IN (SELECT doc FROM allowed) ORDER BY bm25(texts),rowid", (expression,))] if expression else []
    durations["bm25"] = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    scores = vectors @ query_vector
    dense = sorted(allowed, key=lambda i: (-float(scores[i]), i))
    # Full candidate rankings avoid a hidden fetch-limit advantage. At this
    # corpus size exact scans are sufficient; ANN is a separate future test.
    durations["dense"] = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    fused = defaultdict(float)
    for ranking in (bm25, dense):
        for rank, index in enumerate(ranking, 1):
            fused[index] += 1 / (60 + rank)
    hybrid = sorted(fused, key=lambda i: (-fused[i], i))[:k]
    durations["dense_bm25_rrf"] = durations["bm25"] + durations["dense"] + (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    sql = [r[0] for r in db.execute("SELECT DISTINCT doc FROM facts WHERE kind=? AND doc IN (SELECT doc FROM allowed) ORDER BY doc", (case["event_kind"],))]
    durations["sql_reference"] = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    graph = [r[0] for r in db.execute("SELECT DISTINCT p.doc FROM paths p JOIN events e ON p.event=e.id WHERE e.kind=? AND p.doc IN (SELECT doc FROM allowed) ORDER BY p.doc", (case["event_kind"],))]
    durations["graph_path_reference"] = (time.perf_counter() - started) * 1000
    return {"bm25": bm25[:k], "dense": dense[:k], "dense_bm25_rrf": hybrid,
            "sql_reference": sql[:k], "graph_path_reference": graph[:k]}, {method: elapsed + preparation_ms for method, elapsed in durations.items()}


def encode(model, texts):
    import numpy as np
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
    tokenizer.no_truncation()
    tokenizer.no_padding()
    max_length = model.model.tokenizer.truncation["max_length"]
    chunk_size = max_length - tokenizer.num_special_tokens_to_add(False) - 8
    chunks, owners = [], []
    for i, text in enumerate(texts):
        offsets = tokenizer.encode(text, add_special_tokens=False).offsets
        if not offsets:
            raise ValueError("Empty embedding input")
        for start in range(0, len(offsets), chunk_size):
            end = min(start + chunk_size, len(offsets)) - 1
            part = text[offsets[start][0]:offsets[end][1]]
            if len(tokenizer.encode(part).ids) > max_length:
                raise ValueError("Chunk would be silently truncated")
            chunks.append(part)
            owners.append(i)
    embedded = list(model.embed(chunks, batch_size=32))
    result = np.zeros((len(texts), len(embedded[0])), dtype=np.float32)
    counts = Counter(owners)
    for owner, vector in zip(owners, embedded):
        result[owner] += vector
    for i in range(len(result)):
        result[i] /= counts[i]
    norms = np.linalg.norm(result, axis=1, keepdims=True)
    if not np.isfinite(result).all() or (norms == 0).any():
        raise ValueError("Invalid embedding")
    return result / norms, {"chunks": len(chunks), "max_length": max_length, "chunk_tokens": chunk_size, "pooling": "equal mean of all chunk embeddings, then L2 normalize"}


def run(args):
    from fastembed import TextEmbedding
    import numpy as np
    docs = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
    dataset = json.loads(args.queries.read_text())
    validate_inputs(docs, dataset)
    corpus_hash, query_hash = digest(args.corpus), digest(args.queries)
    packet = json.loads(args.qrels.read_text()) if args.qrels else None
    labels = reviewed_qrels(packet, docs, dataset, corpus_hash, query_hash)
    reviewer_kind = (packet or {}).get("reviewer_kind", "unspecified")
    if reviewer_kind == "ai_assisted" and not getattr(args, "allow_ai_reviewed", False):
        raise ValueError("AI-reviewed labels require --allow-ai-reviewed; they are not independent human judgments")
    if labels is None and not args.allow_unreviewed:
        raise ValueError("Independent qrels review is incomplete; use --allow-unreviewed only for an explicitly unscored smoke run")
    start = time.perf_counter()
    model = TextEmbedding(MODEL, local_files_only=True, threads=2, specific_model_path=str(args.model_dir) if args.model_dir else None)
    model_dir = Path(model.model._model_dir)
    artifacts = {str(p.relative_to(model_dir)): digest(p) for p in sorted(model_dir.rglob("*")) if p.is_file()}
    model_load_ms = (time.perf_counter() - start) * 1000
    print(f"Embedding {len(docs)} rounds locally (no model download or remote LLM)", flush=True)
    start = time.perf_counter()
    vectors, chunks = encode(model, [d["text"] for d in docs])
    embedding_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    db = build_index(docs)
    index_ms = (time.perf_counter() - start) * 1000
    page_bytes = db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]
    start = time.perf_counter()
    query_vectors, query_times, query_chunks = [], [], []
    for case in dataset["cases"]:
        start = time.perf_counter()
        encoded, chunk_info = encode(model, [case["query"]])
        query_vectors.append(encoded[0])
        query_times.append((time.perf_counter() - start) * 1000)
        query_chunks.append(chunk_info)
    rows = []
    for constraint in (False, True):
        for index, case in enumerate(dataset["cases"]):
            durations, found = defaultdict(list), None
            for _ in range(args.repeats):
                current, elapsed = ranks(db, docs, case, constraint, query_vectors[index], vectors, args.k)
                for method, ms in elapsed.items():
                    durations[method].append(ms)
                if found is not None and current != found:
                    raise ValueError("Nondeterministic ranking")
                found = current
            for method, ranked in found.items():
                source_ids = [docs[i]["id"] for i in ranked]
                rows.append({"query_id": case["id"], "method": method, "entity_constraint": constraint,
                             "source_ids": source_ids, "returned": len(source_ids),
                             "condition_precision": statistics.mean(eligible(docs[i], case, True) for i in ranked) if ranked else None,
                             "metrics": metrics(source_ids, labels[case["id"]], args.k) if labels is not None else None,
                             "query_encoding_ms": query_times[index] if method in ("dense", "dense_bm25_rrf") else 0,
                             "first_search_ms": durations[method][0],
                             "warm_search_ms": durations[method][1:]})
    summaries = []
    for method in METHODS:
        for constraint in (False, True):
            subset = [r for r in rows if r["method"] == method and r["entity_constraint"] == constraint]
            summary = {"method": method, "entity_constraint": constraint, "queries": len(subset),
                       "queries_with_results": sum(r["returned"] > 0 for r in subset),
                       "condition_precision_nonempty_macro": statistics.mean(r["condition_precision"] for r in subset if r["condition_precision"] is not None) if any(r["returned"] for r in subset) else None,
                       "quality": None,
                       "warm_search_p50_ms": float(np.percentile([v for r in subset for v in r["warm_search_ms"]], 50)),
                       "warm_search_p95_ms": float(np.percentile([v for r in subset for v in r["warm_search_ms"]], 95)),
                       "query_encoding_p50_ms": statistics.median(r["query_encoding_ms"] for r in subset)}
            if labels is not None:
                summary["quality"] = {}
                for name in ("recall_at_k", "ndcg_at_k", "false_retrieval", "false_abstention"):
                    values = [r["metrics"][name] for r in subset if r["metrics"][name] is not None]
                    summary["quality"][name] = {"mean": statistics.mean(values) if values else None, "n": len(values)}
            summaries.append(summary)
    db.close()
    return {"version": "fair-retrieval-v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "status": ("ai_assisted_labels_evaluation" if reviewer_kind == "ai_assisted" else "reviewed_labels_evaluation") if labels is not None else "engineering_smoke_unreviewed_labels",
            "reviewer_kind": reviewer_kind,
            "corpus_sha256": corpus_hash, "queries_sha256": query_hash, "qrels_sha256": digest(args.qrels) if args.qrels else None,
            "source_sha256": digest(__file__), "dependency_constraints_sha256": digest(Path(__file__).resolve().parent.parent / "requirements-lock.txt"),
            "environment": {"python": platform.python_version(), "platform": platform.platform(), "sqlite": sqlite3.sqlite_version,
                            **{p: importlib.metadata.version(p) for p in ("fastembed", "numpy", "onnxruntime", "tokenizers")}},
            "model": {"name": MODEL, "files_sha256": artifacts, "load_ms": model_load_ms, "threads": 2, "document_chunks": chunks, "query_chunks": query_chunks},
            "index": {"rounds": len(docs), "matches": sorted({d['match_id'] for d in docs}), "embedding_ms": embedding_ms, "sqlite_ms": index_ms,
                      "vector_bytes": vectors.nbytes, "vector_sha256": hashlib.sha256(vectors.tobytes()).hexdigest(), "sqlite_page_bytes": page_bytes,
                      "corpus_bytes": args.corpus.stat().st_size, "query_encoding_total_ms": sum(query_times)},
            "contract": {"k": args.k, "repeats": args.repeats, "text_methods": list(METHODS[:3]), "structured_references": list(METHODS[3:]),
                         "filters": "identical explicit map/match/round prefilters; exact roster entity prefilter toggled for every method",
                         "abstention": "no learned threshold; dense/RRF return top-k whenever eligible candidates exist",
                         "timing": "per-method search includes common prefilter cost; RRF includes both component searches; query encoding measured separately once per query; first search is not a controlled cold-start measurement",
                         "scope": "new experimental adapters, not measurements of production Milvus/GraphRAG endpoints"},
            "summary": summaries, "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--graph-db", type=Path, default=Path("data/graph/cs2_graph.sqlite"))
    prepare.add_argument("--output", type=Path, required=True)
    packet = sub.add_parser("packet")
    packet.add_argument("--corpus", type=Path, required=True)
    packet.add_argument("--queries", type=Path, required=True)
    packet.add_argument("--output", type=Path, required=True)
    evaluate = sub.add_parser("run")
    evaluate.add_argument("--corpus", type=Path, required=True)
    evaluate.add_argument("--queries", type=Path, required=True)
    evaluate.add_argument("--qrels", type=Path)
    evaluate.add_argument("--allow-unreviewed", action="store_true", help="engineering smoke only; suppress all relevance quality metrics")
    evaluate.add_argument("--allow-ai-reviewed", action="store_true", help="explicit AI-assisted evaluation; retain reviewer provenance")
    evaluate.add_argument("--model-dir", type=Path)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--k", type=int, default=5)
    evaluate.add_argument("--repeats", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new artifact path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "prepare":
        print(json.dumps(export_corpus(args.graph_db, args.output), indent=2))
    elif args.command == "packet":
        write_json(args.output, review_packet(args.corpus, args.queries))
    else:
        if args.k < 1 or args.repeats < 2:
            parser.error("k must be positive and repeats at least 2")
        report = run(args)
        write_json(args.output, report)
        print(json.dumps({"status": report["status"], "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
