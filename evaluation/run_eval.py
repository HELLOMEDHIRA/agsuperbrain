"""Super-Brain evaluation harness (RQ1, RQ2, RQ4, footprint).

Drives the agsuperbrain Python API directly so timings are clean.
RQ3 (token-cost vs LLM baseline) is intentionally NOT measured here —
it requires real LLM API runs and answer-quality grading. Don't fabricate.

Usage (run from project root with the agsuperbrain venv active):
    python paper/evaluation/run_eval.py \\
        --repo .  --out paper/evaluation/results.json \\
        --warmup 3 --measure 30
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import shutil
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

# Tier-1 hand-authored extractor coverage (matches paper §III).
TIER1_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp",
    ".cs", ".rb", ".php", ".kt", ".kts", ".swift", ".scala",
}

# A practical sample of Tier-2 (generic-walker) extensions; not exhaustive.
TIER2_EXTS = {
    ".lua", ".pl", ".pm", ".r", ".jl", ".dart", ".elm", ".erl",
    ".ex", ".exs", ".hs", ".ml", ".mli", ".f90", ".f95", ".for",
    ".groovy", ".clj", ".cljs", ".coffee", ".nim", ".v", ".sv",
    ".sh", ".bash", ".zsh", ".ps1", ".sql",
}


def now() -> float:
    return time.perf_counter()


def fmt_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def walk_corpus(root: Path) -> tuple[Counter, list[Path]]:
    """Return (extension counter, list of all source-file paths under root).

    Skips the .agsuperbrain index dir, .git, .venv, and node_modules.
    """
    skip_dirs = {".agsuperbrain", ".git", ".venv", "node_modules", "__pycache__",
                 "dist", "build", ".next", ".tox", "target", ".gradle"}
    exts = Counter()
    files: list[Path] = []
    for p in root.rglob("*"):
        try:
            if p.is_dir():
                continue
            parts = set(p.parts)
            if parts & skip_dirs:
                continue
            ext = p.suffix.lower()
            if not ext:
                continue
            exts[ext] += 1
            files.append(p)
        except OSError:
            continue
    return exts, files


def classify_tier(ext: str) -> str:
    if ext in TIER1_EXTS:
        return "T1"
    if ext in TIER2_EXTS:
        return "T2"
    return "other"


def measure(label: str, fn, warmup: int, n: int) -> dict:
    """Time fn() for warmup+n iterations, return {p50,p95,mean,n,errors}."""
    errs = 0
    for _ in range(warmup):
        try:
            fn()
        except Exception:
            errs += 1
    samples: list[float] = []
    for _ in range(n):
        t0 = now()
        try:
            fn()
        except Exception:
            errs += 1
            continue
        samples.append((now() - t0) * 1000.0)
    if not samples:
        return {"label": label, "n": 0, "errors": errs}
    samples.sort()
    return {
        "label": label,
        "n": len(samples),
        "errors": errs,
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(0.95 * (len(samples) - 1))], 3),
        "mean_ms": round(statistics.mean(samples), 3),
        "min_ms": round(min(samples), 3),
        "max_ms": round(max(samples), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("paper/evaluation/results.json"))
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--measure", type=int, default=30)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--clean", action="store_true",
                    help="Wipe ./.agsuperbrain/ before ingest for a cold-cache run")
    args = ap.parse_args()

    repo = args.repo.resolve()
    db_dir = repo / ".agsuperbrain" / "graph"
    qdrant_dir = repo / ".agsuperbrain" / "qdrant"

    if args.clean and (repo / ".agsuperbrain").exists():
        print("[eval] cleaning prior index", flush=True)
        shutil.rmtree(repo / ".agsuperbrain")

    db_dir.parent.mkdir(parents=True, exist_ok=True)

    # --- 0. Imports / version ---
    import agsuperbrain
    from agsuperbrain.core.index_pipeline import VectorIndexPipeline
    from agsuperbrain.core.pipeline import CodeGraphPipeline
    from agsuperbrain.extraction.doc_extractor import DocExtractor
    from agsuperbrain.intelligence.context_builder import ContextBuilder
    from agsuperbrain.intelligence.retriever import HybridRetriever
    from agsuperbrain.memory.graph.graph_store import GraphStore
    from agsuperbrain.memory.vector.embedder import TextEmbedder
    from agsuperbrain.memory.vector.vector_store import VectorStore
    from agsuperbrain.preprocessing.doc_parser import DocParser, is_document

    sb_version = getattr(agsuperbrain, "__version__", "unknown")

    # --- 1. Corpus walk ---
    print("[eval] walking corpus", flush=True)
    exts, all_files = walk_corpus(repo)
    by_tier = Counter(classify_tier(e) for e in exts.elements())
    corpus_summary = {
        "root": str(repo),
        "total_files": sum(exts.values()),
        "by_extension": dict(exts.most_common()),
        "by_tier": dict(by_tier),
    }

    # --- 2. Graph ingestion (timed) ---
    print("[eval] running CodeGraphPipeline", flush=True)
    gs = GraphStore(db_dir)
    gs.init_schema()
    t0 = now()
    pipeline = CodeGraphPipeline(gs)
    pipeline.run([repo], verbose=False)
    ingest_seconds = now() - t0

    def cypher_count(label: str, kind: str) -> int:
        try:
            if kind == "node":
                rows = gs.query(f"MATCH (n:{label}) RETURN count(n)")
            else:
                rows = gs.query(f"MATCH ()-[r:{label}]->() RETURN count(r)")
            return int(rows[0][0]) if rows else 0
        except Exception:
            return -1

    extraction = {
        "Module": cypher_count("Module", "node"),
        "Function": cypher_count("Function", "node"),
        "Class": cypher_count("Class", "node"),
        "Document": cypher_count("Document", "node"),
        "Section": cypher_count("Section", "node"),
        "CALLS": cypher_count("CALLS", "edge"),
        "IMPORTS": cypher_count("IMPORTS", "edge"),
        "CONTAINS": cypher_count("CONTAINS", "edge"),
        "DEFINES": cypher_count("DEFINES", "edge"),
    }

    # --- 3a. Document pipeline (timed) ---
    print("[eval] running DocExtractor pipeline", flush=True)
    doc_files = [p for p in all_files if is_document(p)]
    parser = DocParser()
    doc_extractor = DocExtractor()
    t0 = now()
    doc_ok = doc_failed = 0
    doc_errors: list[dict] = []
    for fp in doc_files:
        try:
            pr = parser.parse(fp)
            ex = doc_extractor.extract(pr)
            gs.upsert_doc(ex)
            doc_ok += 1
        except Exception as e:
            doc_failed += 1
            # Truncate error string; some markitdown errors are noisy.
            doc_errors.append({"file": str(fp.relative_to(repo) if str(fp).startswith(str(repo)) else fp),
                                "error": str(e)[:200]})
    doc_seconds = now() - t0

    extraction["Section"] = cypher_count("Section", "node")
    extraction["Concept"] = cypher_count("Concept", "node")
    extraction["Document"] = cypher_count("Document", "node")

    # --- 3b. RQ4 — per-extension extraction coverage (code + doc) ---
    print("[eval] computing per-extension coverage", flush=True)
    func_rows = gs.query("MATCH (f:Function) RETURN DISTINCT f.source_path")
    files_with_func: set[str] = {str(r[0]) for r in func_rows if r and r[0]}
    sec_rows = gs.query("MATCH (s:Section) RETURN DISTINCT s.source_path")
    files_with_sec: set[str] = {str(r[0]) for r in sec_rows if r and r[0]}

    coverage_by_ext: dict[str, dict] = {}
    files_per_ext: dict[str, set[str]] = {}
    for f in all_files:
        files_per_ext.setdefault(f.suffix.lower(), set()).add(str(f))
    for ext, fileset in files_per_ext.items():
        if exts.get(ext, 0) < 5:  # only report if meaningful sample
            continue
        with_func = sum(1 for f in fileset if f in files_with_func)
        with_sec = sum(1 for f in fileset if f in files_with_sec)
        tier = classify_tier(ext)
        # Pipeline label: code-pipeline targets vs doc-pipeline targets.
        is_doc_ext = ext in {".md", ".html", ".htm", ".pdf", ".docx", ".pptx", ".txt", ".rst"}
        coverage_by_ext[ext] = {
            "tier": tier,
            "pipeline": "doc" if is_doc_ext else ("code" if tier in ("T1", "T2") else "none"),
            "files": len(fileset),
            "files_with_extracted_function": with_func,
            "files_with_extracted_section": with_sec,
            "coverage_func_pct": round(100.0 * with_func / len(fileset), 1) if len(fileset) else 0.0,
            "coverage_section_pct": round(100.0 * with_sec / len(fileset), 1) if len(fileset) else 0.0,
        }

    # --- 4. Vector index (timed) ---
    print("[eval] running VectorIndexPipeline", flush=True)
    vs = VectorStore(db_path=qdrant_dir)
    emb = TextEmbedder()
    t0 = now()
    vector_count = VectorIndexPipeline(gs, vs, emb).run(incremental=True)
    vector_seconds = now() - t0

    # --- 5. Storage footprint ---
    storage = {
        "kuzu_bytes": dir_size(db_dir),
        "qdrant_bytes": dir_size(qdrant_dir),
        "total_bytes": dir_size(repo / ".agsuperbrain"),
        "kuzu_human": fmt_size(dir_size(db_dir)),
        "qdrant_human": fmt_size(dir_size(qdrant_dir)),
        "total_human": fmt_size(dir_size(repo / ".agsuperbrain")),
    }

    # --- 6. RQ2 — query latency ---
    print("[eval] measuring query latency", flush=True)
    retriever = HybridRetriever(gs, vs, emb)
    ContextBuilder()  # ensure import path is healthy

    # Sample function IDs for graph queries
    func_rows = gs.query("MATCH (f:Function) RETURN f.id LIMIT 200")
    func_ids = [str(r[0]) for r in func_rows if r and r[0]]
    rng = random.Random(42)
    rng.shuffle(func_ids)
    sample_ids = func_ids[: max(args.measure, 30)]

    # Vector seed query strings — derived from corpus, not invented:
    # use random function names already in the graph as semantic queries.
    name_rows = gs.query("MATCH (f:Function) RETURN f.name LIMIT 500")
    names = [str(r[0]) for r in name_rows if r and r[0]]
    rng.shuffle(names)
    query_strs = names[: max(args.measure, 30)] or ["function", "class", "init"]

    qs_iter = iter(query_strs * 3)
    ids_iter = iter(sample_ids * 3)

    def _next_q():
        return next(qs_iter, "function")

    def _next_id():
        return next(ids_iter, sample_ids[0] if sample_ids else "")

    latency = {}

    def search_code():
        retriever.query(_next_q(), top_k=args.top_k, node_type="Function")

    def vec_only():
        emb.embed([_next_q()])

    def find_callers():
        fid = _next_id()
        if not fid:
            return
        gs.query(
            "MATCH (caller:Function)-[:CALLS]->(callee:Function {id:$fid}) "
            "RETURN caller.id, caller.qualified_name LIMIT 100",
            {"fid": fid},
        )

    def find_callees():
        fid = _next_id()
        if not fid:
            return
        gs.query(
            "MATCH (caller:Function {id:$fid})-[:CALLS]->(callee:Function) "
            "RETURN callee.id, callee.qualified_name LIMIT 100",
            {"fid": fid},
        )

    def closure_query():
        fid = _next_id()
        if not fid:
            return
        gs.query(
            "MATCH (root:Function {id:$fid})-[:CALLS*1..3]->(d:Function) "
            "RETURN DISTINCT d.id LIMIT 200",
            {"fid": fid},
        )

    latency["embed_only"] = measure("embed_only", vec_only, args.warmup, args.measure)
    latency["search_code"] = measure("search_code", search_code, args.warmup, args.measure)
    latency["find_callers"] = measure("find_callers", find_callers, args.warmup, args.measure)
    latency["find_callees"] = measure("find_callees", find_callees, args.warmup, args.measure)
    latency["closure_d3"] = measure("closure_d3", closure_query, args.warmup, args.measure)

    # --- 7. Assemble result ---
    result = {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "agsuperbrain_version": sb_version,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "cpu_count": (lambda: __import__("os").cpu_count())(),
            "warmup": args.warmup,
            "measure_n": args.measure,
            "top_k": args.top_k,
        },
        "corpus": corpus_summary,
        "ingestion": {
            "wall_seconds": round(ingest_seconds, 3),
            "throughput_files_per_sec": round(corpus_summary["total_files"] / ingest_seconds, 2)
            if ingest_seconds > 0 else None,
        },
        "doc_ingestion": {
            "wall_seconds": round(doc_seconds, 3),
            "files_attempted": len(doc_files),
            "files_ok": doc_ok,
            "files_failed": doc_failed,
            "errors": doc_errors[:10],  # truncate to keep JSON readable
        },
        "extraction": extraction,
        "vector_index": {
            "wall_seconds": round(vector_seconds, 3),
            "total_vectors": vector_count,
        },
        "storage": storage,
        "coverage_by_extension": coverage_by_ext,
        "latency": latency,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(f"[eval] wrote {args.out}", flush=True)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
