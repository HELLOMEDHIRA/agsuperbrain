# Architecture

A high-level tour of how Super-Brain turns raw code into a queryable knowledge graph.

---

## The five layers

Super-Brain is organized as five cooperating layers. Each has a single job and a clean contract with the next.

```
┌──────────────────────────────────────────────────┐
│  5. Interface      CLI · MCP server · Reports    │
├──────────────────────────────────────────────────┤
│  4. Intelligence   Hybrid retriever · LLM · Tools│
├──────────────────────────────────────────────────┤
│  3. Storage        KùzuDB graph + Qdrant vectors │
├──────────────────────────────────────────────────┤
│  2. Extraction     Deterministic AST parsers     │
├──────────────────────────────────────────────────┤
│  1. Preprocessing  Tree-sitter · MarkItDown      │
│                    · faster-whisper · yt-dlp     │
└──────────────────────────────────────────────────┘
```

Everything below layer 4 is deterministic. No LLM calls happen during ingestion.

---

## Layer 1 — Preprocessing

**Job**: turn raw inputs (code files, documents, audio) into parsed intermediate representations.

- **Code** — [tree-sitter](https://tree-sitter.github.io) with [tree-sitter-language-pack](https://github.com/Goldziher/tree-sitter-language-pack). 306 languages, one consistent AST interface.
- **Documents** — [MarkItDown](https://github.com/microsoft/markitdown) converts PDF, DOCX, PPTX, MD, TXT, HTML into normalized markdown with headings preserved.
- **Audio / video** — [yt-dlp](https://github.com/yt-dlp/yt-dlp) fetches remote sources; [FFmpeg](https://ffmpeg.org) normalizes to WAV; [faster-whisper](https://github.com/SYSTRAN/faster-whisper) transcribes locally with word-level timestamps.

No network calls happen here unless the user explicitly asks for a YouTube URL. Transcription runs entirely on-device.

---

## Layer 2 — Extraction

**Job**: turn parsed trees and transcripts into graph-ready entities and edges.

- **Rule-based AST queries** produce Function, Method, and Class nodes along with their call edges. Rules are language-specific for tier-1 languages and generic for the other 290+.
- **Import resolution** links symbols across files by resolving relative and absolute imports.
- **Document extraction** breaks markdown into Section nodes, one per heading, preserving the heading hierarchy.
- **Audio extraction** chunks transcripts into Transcript nodes with start/end timestamps.

Every extraction rule is deterministic. Given the same input, you get identical output every run — which means you can commit the graph, diff it, and trust it.

---

## Layer 3 — Storage

**Job**: persist extracted nodes and edges; serve them to the query layer with low latency.

Two stores work together:

### KùzuDB — the graph

[KùzuDB](https://kuzudb.com) is an embedded graph database. No server, no daemon. The whole database is a file (or a directory of files) in your project. Supports Cypher, ACID transactions, and multi-gigabyte graphs on commodity hardware.

Node types: `Module`, `Function`, `Class`, `Document`, `Section`, `Concept`, `Audio`, `Transcript`.

Edge types: `CALLS`, `DEFINES`, `IMPORTS`, `CONTAINS`, `REFERENCES`, `TRANSCRIBES`, `LINKED_TO`.

### Qdrant — the vector store

Local-mode [Qdrant](https://qdrant.tech), same story: embedded, file-backed, no server required. Holds 384-dimensional embeddings produced by a local [sentence-transformer](https://www.sbert.net) model (default: `all-MiniLM-L6-v2`).

Every node that has meaningful text (function body, doc section, transcript) is embedded and cross-indexed by `node_id` with the graph.

---

## Layer 4 — Intelligence

**Job**: answer questions by combining semantic similarity with structural traversal.

### Hybrid retrieval

1. **Semantic seed**: vector-search the query against Qdrant. Returns top-K candidates ranked by cosine similarity.
2. **Graph expansion**: for each seed, walk the graph outward (`CALLS`, `LINKED_TO`, `REFERENCES`) to a configurable depth. Each hop applies a decay factor so structurally-distant nodes don't swamp the result.
3. **Filter and rank**: exclude external stubs, merge duplicates, sort by decayed score.

The result is a ranked list of nodes with source paths, line numbers, and confidence — enough evidence to cite exactly why the answer is what it is.

### Optional local LLM

For rich natural-language answers, an optional [llama.cpp](https://github.com/ggerganov/llama.cpp) integration runs [Llama-3.2-1B](https://ai.meta.com/blog/llama-3-2-connect-2024-vision-edge-mobile-devices/) locally (~700 MB model file, downloaded once). The LLM receives only the ranked evidence bundle — never the whole codebase — and composes the prose.

Turning the LLM off gives you pure deterministic evidence. Turning it on adds phrasing, not facts.

---

## Layer 5 — Interface

**Job**: expose the intelligence layer to humans and other tools.

Three entry points:

- **CLI** — `agsuperbrain ask`, `search-vectors`, `query`, `inspect-function`, and everything else in the [CLI Reference](cli.md).
- **MCP server** — `agsuperbrain mcp-serve` over stdio JSON-RPC. Ten tools: `search_code`, `find_callers`, `find_callees`, `get_function_body`, `path_between`, `closure`, `get_subgraph`, `stats`, `list_modules`, `list_functions`.
- **Reports** — `agsuperbrain report` writes a `GRAPH_REPORT.md` with god-nodes, cross-module dependencies, orphans, and suggested follow-up questions. `init` and the background watcher regenerate `.agsuperbrain/GRAPH_REPORT.md` and `.agsuperbrain/graph.html` automatically after every re-index.

All three read from the same graph and vector store. There is no second copy of anything.

---

## Data flow end to end

```
Source files ──► tree-sitter ──► Function/Call nodes ──┐
                                                       ├──► KùzuDB ──┐
PDFs / docs  ──► MarkItDown  ──► Section nodes       ──┤             │
                                                       │             ├──► Hybrid retriever ──► MCP / CLI
Audio / video ─► Whisper    ──► Transcript nodes     ──┘             │
                                                                     │
Node text     ──► sentence-transformers ──► 384-dim vectors ──► Qdrant ┘
```

Ingestion is one-way and additive. Query-time reads are cheap. The file watcher re-runs the ingestion pipeline only against changed files, keeping the graph fresh without a full rebuild.

---

## Determinism guarantees

The architecture is built to keep surprises out:

- **No LLM in ingestion.** Call edges, class hierarchies, imports — all come from AST walks. An LLM cannot invent a relationship that isn't in the code.
- **Stable node IDs.** IDs are derived from source path + qualified name, so re-ingesting the same code produces the same graph.
- **Transactional writes.** KùzuDB is ACID. A crash mid-ingest leaves the previous graph intact.
- **Idempotent upserts.** Re-running `ingest` on the same files updates changed bodies and leaves everything else alone.

---

## Performance characteristics

Measured on a self-corpus pilot (the `agsuperbrain` repository itself, 131 files, 86 Tier-1 source files; x86_64, 8 vCPU under WSL2, ext4). Reproducible via [`paper/evaluation/run_eval.py`](https://github.com/HELLOMEDHIRA/agsuperbrain/blob/main/paper/evaluation/run_eval.py).

**Query latency** (n=30 per primitive, 3 warmup):

| Operation | p50 | p95 |
|---|---:|---:|
| `find_callers` (Cypher graph traversal) | 2.0 ms | 2.5 ms |
| `find_callees` (Cypher graph traversal) | 2.3 ms | 3.1 ms |
| `closure` (depth 3, transitive) | 4.3 ms | 7.4 ms |
| `embed_only` (warm sentence-transformer) | 7.1 ms | 9.0 ms |
| `search_code` (hybrid: vector seed + graph expansion) | 491 ms | 781 ms |

**Cold-start cost** (one-time, then incremental):

| Phase | Wall time |
|---|---:|
| Code ingest (Pass A indexing + Pass B call resolution) | 488.7 s |
| Document ingest (`.md`, `.html`, `.pdf`, `.docx`, `.pptx`) | 34.5 s |
| Vector indexing (2,973 nodes, 384-dim) | 109.4 s |

**Storage footprint:** 22.9 MiB total on disk (KùzuDB graph + Qdrant vector store) for 5.4 MiB of indexed source/doc content.

**Steady state:** the file watcher debounces changes (default 400 ms) and re-indexes only the affected files — typically milliseconds per change. Pass-B call resolution on large repos is the primary candidate for optimisation in upcoming releases.

Latency and throughput vary with file size, language, and hardware. Pilot scope and full caveats are in [the paper](https://github.com/HELLOMEDHIRA/agsuperbrain/blob/main/paper/super-brain.md#5-evaluation).

---

## What's intentionally out of scope

Super-Brain is not:

- A code generator — it indexes code, it doesn't write code
- A cloud service — there is no Super-Brain server to log into
- A replacement for your assistant — it makes your assistant smarter, not redundant
- A type checker — it extracts structural facts, not type correctness

---

## Next steps

- [CLI Reference](cli.md) — commands built on this architecture
- [IDE Integration](mcp.md) — how the architecture plugs into Claude Code / Cursor / Aider / etc.
- [Why Super-Brain](comparison.md) — what this architecture solves that standalone assistants can't
