"""RQ3 pilot: token-cost reduction, context-stuffing baseline vs Super-Brain bundle.

For each query, runs two completions against the same LLM
(default: Groq llama-3.3-70b-versatile):

  baseline   prompt = code corpus packed up to MAX_PROMPT_TOKENS_BASELINE
             (no retrieval; deterministic lex order; truncated when full)
  superbrain prompt = evidence retrieved by HybridRetriever + ContextBuilder

Records prompt/completion tokens for each, plus an LLM-as-judge score
(0--5) of each answer's correctness against a reference answer.

Caveats baked into the output:
  - Judge model == answerer model (Llama 3.3 70B). This is known weak
    grading (circular). Treat scores as upper-bound estimates and mark
    them as such in any paper that cites these numbers.
  - Single LLM (M=1). The §V.C protocol calls for replication across
    multiple assistants; this is a pilot toward that, not the full study.
  - Baseline is "context-stuffing" not "agentic file-reading like Claude
    Code." The headline ratio is an upper bound on the cost of a naive
    no-retrieval approach.

Usage (from ~/agsbrepo with the agsuperbrain venv):
    GROQ_API_KEY=sk_... python paper/evaluation/run_rq3.py \
        --repo . --out paper/evaluation/results_rq3.json \
        --reps 1
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_DEFAULT = "llama-3.3-70b-versatile"

# Llama 3.3 70B Versatile on Groq has 32k context; cap input well below
# that to leave room for completion.
MAX_PROMPT_CHARS_BASELINE = 90_000   # ~22k tokens at 4 chars/token
MAX_PROMPT_CHARS_SB = 30_000         # ~7.5k tokens
MAX_COMPLETION_TOKENS = 512


QUERIES: list[dict] = [
    {
        "id": "Q01",
        "question": "What does the _do_full_init function do, and what major operations does it perform in order?",
        "category": "lookup",
        "reference": (
            "_do_full_init writes the project config scaffold, optionally runs a "
            "dependency preflight (offering pip install), runs CodeGraphPipeline "
            "to ingest source code, runs VectorIndexPipeline to embed nodes, "
            "generates reports, and starts the background watcher. It is the "
            "shared body used by both the `init` command and _ensure_initialized."
        ),
    },
    {
        "id": "Q02",
        "question": "Which CLI commands start the background watcher, and which one starts it implicitly via _ensure_initialized?",
        "category": "navigation",
        "reference": (
            "The `init` command starts the watcher explicitly via "
            "_start_watcher_background. The 14 IDE installers (claude-install, "
            "cursor-install, aider-install, etc.) start it implicitly through "
            "_ensure_initialized when the project has not been set up yet. "
            "The `watch` command runs the watcher in foreground."
        ),
    },
    {
        "id": "Q03",
        "question": "How does the HybridRetriever combine vector search with graph expansion?",
        "category": "reasoning",
        "reference": (
            "HybridRetriever first embeds the query and retrieves top-k "
            "vectors from Qdrant (the seeds). For each seed it expands along "
            "the graph using a per-node-type Cypher template (CALLS for "
            "Function, CONTAINS for Section, FOLLOWS for Transcript) up to a "
            "configurable depth. Each graph-discovered neighbour gets a "
            "decayed score s * gamma^h where s is the seed's vector score "
            "and h is the hop distance. Results merge by node_id and sort by "
            "final score. FTS keyword hits also contribute via search_fts."
        ),
    },
    {
        "id": "Q04",
        "question": "What does `agsuperbrain clean` do?",
        "category": "lookup",
        "reference": (
            "The clean command stops the running watcher (via _stop_watcher) "
            "and then deletes the entire .agsuperbrain directory, wiping all "
            "Super-Brain state for the project (graph, vectors, audio cache, "
            "config, watcher status)."
        ),
    },
    {
        "id": "Q05",
        "question": "How does _ensure_initialized differ from the `init` command?",
        "category": "reasoning",
        "reference": (
            "_ensure_initialized is a self-healing helper used by the IDE "
            "installer commands. It checks for .agsuperbrain/ and "
            ".agsuperbrainignore; if absent, it calls _do_full_init with "
            "show_next_steps=False (no trailing 'Next:' guidance, since the "
            "installer prints its own). The `init` command invokes "
            "_do_full_init with show_next_steps=True. Both share the same "
            "implementation body so behaviour cannot drift."
        ),
    },
    {
        "id": "Q06",
        "question": "What does the find_callers MCP tool do, and what Cypher pattern does it run?",
        "category": "lookup",
        "reference": (
            "find_callers returns all functions that call a given function, "
            "identified by node id. It runs a Cypher query of the form "
            "MATCH (caller:Function)-[:CALLS]->(callee:Function {id:$fid}) "
            "RETURN caller.id, caller.qualified_name, caller.source_path."
        ),
    },
    {
        "id": "Q07",
        "question": "Which IDE installer commands write an MCP server config (e.g., mcp.json) and which only write a rules/skill file?",
        "category": "navigation",
        "reference": (
            "MCP-config writers include claude-install (.claude/settings.json "
            "mcpServers), cursor-install (.cursor/mcp.json), aider-install "
            "(.aider.conf.yml mcp-servers), gemini-install, codex-install, "
            "opencode-install, and similar. Rule/skill-only installers (those "
            "for tools without first-class MCP) write a Markdown rule file and "
            "rely on the user's existing MCP wiring. The exact split is "
            "encoded in cli.py's per-installer functions."
        ),
    },
    {
        "id": "Q08",
        "question": "What is in the watcher status JSON file, and which field is used to determine liveness?",
        "category": "lookup",
        "reference": (
            "The status JSON at .agsuperbrain/watcher.status.json is written "
            "by FileWatcher and contains state, pid, backend (\"watchfiles\"), "
            "pending_count / current_batch_size, last_heartbeat_at, "
            "batches_processed, files_processed, worker_alive, and last_error. "
            "Liveness is determined by the age of last_heartbeat_at "
            "(threshold ~30s) combined with PID-alive checks; worker_alive "
            "alone can be stale."
        ),
    },
    {
        "id": "Q09",
        "question": "How does the VectorIndexPipeline decide which graph nodes to embed?",
        "category": "reasoning",
        "reference": (
            "VectorIndexPipeline iterates over node tables that carry "
            "meaningful text (Module, Function, Section, Concept, Transcript) "
            "and embeds rows whose text is non-empty. In incremental mode it "
            "embeds only nodes not already present in the Qdrant collection, "
            "matched by node_id. Embeddings are 384-dim from "
            "all-MiniLM-L6-v2."
        ),
    },
    {
        "id": "Q10",
        "question": "What node labels and edge labels does the KùzuDB graph schema declare?",
        "category": "lookup",
        "reference": (
            "Node labels: Module, Function, Class, Document, Section, "
            "Concept, Audio, Transcript. Edge labels include CALLS, DEFINES, "
            "IMPORTS, CONTAINS, REFERENCES, TRANSCRIBES, LINKED_TO. The "
            "schema is declared once via a DDL script in graph_store and is "
            "idempotent on re-application."
        ),
    },
]


def call_groq(api_key: str, model: str, messages: list, max_tokens: int) -> dict:
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GROQ_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Default urllib UA is fingerprint-blocked by Cloudflare (err 1010).
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        return {"error": {"status": e.code, "body": err_body}}
    except urllib.error.URLError as e:
        return {"error": {"status": "url_error", "body": str(e)}}


def collect_code_files(root: Path, exts: set[str]) -> list[Path]:
    skip = {".agsuperbrain", ".git", ".venv", "node_modules", "__pycache__",
            "dist", "build", "output"}
    out = []
    for p in sorted(root.rglob("*"), key=lambda x: str(x)):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
            continue
        if p.suffix.lower() in exts:
            out.append(p)
    return out


def build_baseline_prompt(corpus_root: Path, question: str) -> tuple[list, dict]:
    files = collect_code_files(corpus_root, {".py", ".js"})
    blocks: list[str] = []
    used = 0
    skipped_oversized = 0
    n_included = 0
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f.relative_to(corpus_root) if str(f).startswith(str(corpus_root)) else f
        block = f"\n\n# === FILE: {rel} ===\n{text}"
        # Skip individual files that wouldn't fit on their own — a real
        # agent reading file-by-file behaves the same way (it would
        # paginate or skip rather than abort the whole read pass).
        if len(block) > MAX_PROMPT_CHARS_BASELINE:
            skipped_oversized += 1
            continue
        if used + len(block) > MAX_PROMPT_CHARS_BASELINE:
            # Cap reached. Don't break — there may be smaller files later
            # that still fit in the remaining budget.
            continue
        blocks.append(block)
        used += len(block)
        n_included += 1
    truncated = (n_included < len(files) - skipped_oversized)
    system = (
        "You are a code assistant. The user has pasted the contents of a "
        "code repository below. Answer the question based only on that code. "
        "Be concise: 2 to 4 sentences. Cite specific function names where helpful."
    )
    user = "".join(blocks) + f"\n\n# Question\n{question}"
    meta = {
        "files_total": len(files),
        "files_included": n_included,
        "files_skipped_oversized": skipped_oversized,
        "truncated": truncated,
        "prompt_chars": len(user),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], meta


def build_superbrain_prompt(tools, question: str) -> tuple[list, dict]:
    response = tools.search(question)
    evidence = response.evidence
    blocks: list[str] = []
    used = 0
    n_included = 0
    truncated = False
    for ev in evidence:
        path = ev.get("source_path", "")
        text = ev.get("text", "")
        node_type = ev.get("node_type", "")
        block = f"\n\n# === {node_type} @ {path} ===\n{text}"
        if used + len(block) > MAX_PROMPT_CHARS_SB:
            truncated = True
            break
        blocks.append(block)
        used += len(block)
        n_included += 1
    system = (
        "You are a code assistant. Below is evidence retrieved from a code "
        "repository's knowledge graph (Super-Brain). Answer the question "
        "based only on this evidence. Be concise: 2 to 4 sentences. Cite "
        "specific function names where helpful."
    )
    user = "# Evidence\n" + "".join(blocks) + f"\n\n# Question\n{question}"
    meta = {
        "evidence_total": len(evidence),
        "evidence_included": n_included,
        "truncated": truncated,
        "prompt_chars": len(user),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], meta


def judge(api_key: str, model: str, question: str, reference: str, candidate: str) -> dict:
    """Score candidate answer 0--5 against reference using same LLM."""
    sys_msg = (
        "You are an impartial grader of short technical answers. Given a "
        "question, a reference answer, and a candidate answer, score the "
        "candidate from 0 to 5 on factual correctness:\n"
        "  5 = covers all factual points in the reference, no errors\n"
        "  4 = mostly correct, minor omission\n"
        "  3 = partially correct, one significant omission or minor error\n"
        "  2 = partially correct, multiple omissions or one significant error\n"
        "  1 = mostly incorrect or contains hallucinated claims\n"
        "  0 = completely wrong or refuses to answer\n"
        "Respond with JSON only: {\"score\": <int 0-5>, \"why\": \"<brief>\"}"
    )
    user_msg = (
        f"# Question\n{question}\n\n"
        f"# Reference answer\n{reference}\n\n"
        f"# Candidate answer\n{candidate}\n\n"
        "Score:"
    )
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]
    resp = call_groq(api_key, model, messages, max_tokens=200)
    if "error" in resp:
        return {"score": None, "why": f"judge error: {resp['error']}"}
    text = resp["choices"][0]["message"]["content"].strip()
    # Be liberal in parsing — strip code fences if present.
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        # Sometimes the model wraps JSON in prose; extract the {...}.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        obj = json.loads(text)
        score = int(obj.get("score"))
        why = str(obj.get("why", ""))[:300]
        return {"score": score, "why": why}
    except Exception as e:
        return {"score": None, "why": f"parse error: {e}; raw: {text[:200]}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--out", type=Path, default=Path("paper/evaluation/results_rq3.json"))
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--reps", type=int, default=1, help="repetitions per query (mean is reported)")
    args = ap.parse_args()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY env var not set", file=sys.stderr)
        return 2

    repo = args.repo.resolve()
    db_dir = repo / ".agsuperbrain" / "graph"
    qdrant_dir = repo / ".agsuperbrain" / "qdrant"

    if not db_dir.exists() or not qdrant_dir.exists():
        print(
            f"ERROR: indices not found at {db_dir} / {qdrant_dir}. "
            "Run run_eval.py first (to ingest + index).",
            file=sys.stderr,
        )
        return 3

    # Lazy imports — avoid pulling agsuperbrain when only printing help.
    from agsuperbrain.intelligence.context_builder import ContextBuilder
    from agsuperbrain.intelligence.retriever import HybridRetriever
    from agsuperbrain.intelligence.tools import SuperBrainTools
    from agsuperbrain.memory.graph.graph_store import GraphStore
    from agsuperbrain.memory.vector.embedder import TextEmbedder
    from agsuperbrain.memory.vector.vector_store import VectorStore

    gs = GraphStore(db_dir)
    gs.init_schema()
    vs = VectorStore(db_path=qdrant_dir)
    emb = TextEmbedder()
    retriever = HybridRetriever(gs, vs, emb)
    cb = ContextBuilder()
    tools = SuperBrainTools(retriever, cb, top_k=5, llm_engine=None)

    results: list[dict] = []
    for q in QUERIES:
        print(f"[rq3] {q['id']}: {q['question'][:70]}", flush=True)
        per_rep: list[dict] = []
        for rep in range(args.reps):
            # ---- baseline ----
            base_msgs, base_meta = build_baseline_prompt(repo, q["question"])
            t0 = time.perf_counter()
            base_resp = call_groq(api_key, args.model, base_msgs, MAX_COMPLETION_TOKENS)
            base_wall = time.perf_counter() - t0
            if "error" in base_resp:
                base_record = {"error": base_resp["error"], "wall_s": base_wall, **base_meta}
                base_answer = ""
            else:
                ch = base_resp["choices"][0]["message"]["content"]
                usage = base_resp.get("usage", {})
                base_record = {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "wall_s": round(base_wall, 3),
                    "answer": ch,
                    **base_meta,
                }
                base_answer = ch

            # ---- super-brain ----
            sb_msgs, sb_meta = build_superbrain_prompt(tools, q["question"])
            t0 = time.perf_counter()
            sb_resp = call_groq(api_key, args.model, sb_msgs, MAX_COMPLETION_TOKENS)
            sb_wall = time.perf_counter() - t0
            if "error" in sb_resp:
                sb_record = {"error": sb_resp["error"], "wall_s": sb_wall, **sb_meta}
                sb_answer = ""
            else:
                ch = sb_resp["choices"][0]["message"]["content"]
                usage = sb_resp.get("usage", {})
                sb_record = {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "wall_s": round(sb_wall, 3),
                    "answer": ch,
                    **sb_meta,
                }
                sb_answer = ch

            # ---- judge ----
            j_base = judge(api_key, args.model, q["question"], q["reference"], base_answer)
            j_sb = judge(api_key, args.model, q["question"], q["reference"], sb_answer)

            per_rep.append(
                {
                    "rep": rep,
                    "baseline": base_record,
                    "superbrain": sb_record,
                    "judge_baseline": j_base,
                    "judge_superbrain": j_sb,
                }
            )

        # Aggregate across reps if reps > 1.
        results.append(
            {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "reps": per_rep,
            }
        )

    # ---- aggregate stats ----
    base_in_tokens: list[int] = []
    sb_in_tokens: list[int] = []
    base_out_tokens: list[int] = []
    sb_out_tokens: list[int] = []
    base_scores: list[int] = []
    sb_scores: list[int] = []
    for r in results:
        for rep in r["reps"]:
            b, s = rep["baseline"], rep["superbrain"]
            if isinstance(b.get("prompt_tokens"), int):
                base_in_tokens.append(b["prompt_tokens"])
                base_out_tokens.append(b.get("completion_tokens") or 0)
            if isinstance(s.get("prompt_tokens"), int):
                sb_in_tokens.append(s["prompt_tokens"])
                sb_out_tokens.append(s.get("completion_tokens") or 0)
            jb = rep["judge_baseline"].get("score")
            js = rep["judge_superbrain"].get("score")
            if isinstance(jb, int):
                base_scores.append(jb)
            if isinstance(js, int):
                sb_scores.append(js)

    def safe_mean(xs):
        return round(statistics.mean(xs), 2) if xs else None

    summary = {
        "n_queries": len(results),
        "reps_per_query": args.reps,
        "model": args.model,
        "judge_model": args.model,
        "judge_caveat": (
            "judge model == answerer model; this is known weak grading "
            "(circular). Treat scores as upper-bound estimates."
        ),
        "baseline_prompt_chars_cap": MAX_PROMPT_CHARS_BASELINE,
        "superbrain_prompt_chars_cap": MAX_PROMPT_CHARS_SB,
        "baseline_input_tokens_mean": safe_mean(base_in_tokens),
        "superbrain_input_tokens_mean": safe_mean(sb_in_tokens),
        "baseline_output_tokens_mean": safe_mean(base_out_tokens),
        "superbrain_output_tokens_mean": safe_mean(sb_out_tokens),
        "baseline_total_tokens_sum": sum(base_in_tokens) + sum(base_out_tokens),
        "superbrain_total_tokens_sum": sum(sb_in_tokens) + sum(sb_out_tokens),
        "input_token_ratio_baseline_over_sb": (
            round(safe_mean(base_in_tokens) / safe_mean(sb_in_tokens), 2)
            if base_in_tokens and sb_in_tokens else None
        ),
        "judge_score_baseline_mean": safe_mean(base_scores),
        "judge_score_superbrain_mean": safe_mean(sb_scores),
    }

    output = {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": args.model,
            "repo": str(repo),
            "reps": args.reps,
        },
        "summary": summary,
        "results": results,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True))
    print(f"[rq3] wrote {args.out}", flush=True)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
