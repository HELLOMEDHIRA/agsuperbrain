# Super-Brain

**Your codebase's working memory — local, fast, permanent.**

Super-Brain gives your AI coding assistant a persistent, structured understanding of your code. Instead of re-reading files every turn, your assistant queries a local knowledge graph and gets back the exact functions, call paths, and semantics it needs.

Runs entirely on your machine. Plugs into 14 IDEs and AI coding tools. Zero code leaves your laptop.

---

## The 30-second pitch

AI coding assistants have a context problem. Every session starts from zero. Every question re-reads the same files. Every long task burns tokens on exploration instead of answers.

Super-Brain fixes that. It ingests your code once, builds a call graph and vector index, and exposes it to your assistant via MCP. From then on:

- **"What calls `processPayment`?"** → one graph query, millisecond response
- **"Explain the auth flow"** → retrieve the actual path from HTTP handler to session store
- **"Where's this class used?"** → transitive closure, not grep
- **"Summarize this module"** → pre-clustered subsystems, already grouped

No cloud. No re-ingestion per session. No fabricated call relationships.

---

## Why it's different

| Capability | Claude Code / Codex alone | With Super-Brain |
|---|---|---|
| Call graph understanding | Grep + read files | Deterministic graph query |
| Persistent memory | ❌ Session-scoped | ✅ On disk, always available |
| Token cost per exploration | Proportional to codebase | Flat — queries, not reads |
| Privacy | Uploads code to cloud | Nothing leaves your machine |
| Cross-repo | One project at a time | Ingest multiple, query across |
| Binary/docs/audio | Invisible | First-class via `ingest-doc` / `ingest-audio` |
| Language coverage | Top ~20 | **306** via tree-sitter |

[See the full comparison →](comparison.md)

---

## Install

```bash
pip install agsuperbrain
```

Or with uv:

```bash
uv add agsuperbrain
```

[Full install guide →](install.md)

---

## Quick start

```bash
agsuperbrain init                    # configures + auto-ingests + indexes
agsuperbrain claude-install          # or: cursor-install, aider-install, etc.
```

One command sets up config, detects your source directory, builds the graph, embeds it for semantic search, and starts the background watcher. The second wires Super-Brain into your AI coding tool.

That's it. Your assistant now has permanent, structured access to your codebase.

[Five-minute walkthrough →](quickstart.md)

---

## Works with everything

Super-Brain ships install commands for **14 AI coding tools**:

Claude Code · Cursor · Aider · Codex · OpenCode · GitHub Copilot CLI · VS Code Copilot Chat · Gemini CLI · Hermes · Kiro · Google Antigravity · OpenClaw · Factory Droid · Trae / Trae CN

One command per platform — installs the right hook, skill file, or rules into the right place. [See the IDE matrix →](mcp.md)

Any framework that speaks MCP also works: LangChain, LangGraph, AutoGen, CrewAI, SmolAgents, or plain stdio JSON-RPC.

---

## What it gives you

- **306 language support** — Python, JS/TS, Go, Rust, Java, C/C++, Ruby, PHP, Kotlin, Swift, Scala, and 296 more via tree-sitter
- **Deterministic extraction** — call graph comes from AST, not from an LLM guess
- **Hybrid retrieval** — vector search for semantics + graph expansion for structure
- **Local LLM (optional)** — answer questions using a bundled Llama-3.2-1B model, free and offline
- **Interactive visualization** — Cytoscape.js graph, click to navigate
- **File watcher** — code changes re-indexed automatically
- **Community detection** — Leiden clustering surfaces subsystems without manual tagging
- **Multimodal** — ingest PDFs, DOCX, MD, audio, and video into the same graph

---

## Measured performance

From a self-corpus pilot (the `agsuperbrain` repository itself; reproducible via `paper/evaluation/run_eval.py`).

**Token cost — same 10 questions, same LLM (Llama-3.3-70B):**

![Token cost: 210,659 vs 22,837](../paper/fig5-rq3-token-comparison.png)

- **Without Super-Brain:** 210,659 tokens total (mean 21,066 per question)
- **With Super-Brain:**    22,837 tokens total (mean  2,284 per question)
- **9.22× fewer tokens overall**, comparable answer quality (within noise)

**Extraction & retrieval:**

- **100% extraction** per code-file on Python (40/40) and JavaScript (36/36)
- **90–100% Section coverage** on Markdown and HTML via the document pipeline
- **Sub-3 ms p95** on `find_callers` / `find_callees` graph queries; **7.4 ms p95** on transitive `closure` (depth 3)
- **22.9 MiB on disk** for the full code+doc index of a 5.4 MiB repository

Pilot scope, single-LLM caveat, and full numbers: see [the paper](https://github.com/HELLOMEDHIRA/agsuperbrain/blob/main/paper/super-brain.md#5-evaluation).

---

## Privacy by default

Every byte Super-Brain touches stays on your machine:

- Graph database: local KùzuDB file
- Vector store: local [Qdrant](https://qdrant.tech) directory
- Embeddings: local [sentence-transformers](https://www.sbert.net)
- LLM (optional): local [llama.cpp](https://github.com/ggerganov/llama.cpp)
- Transcription: local [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

Nothing is uploaded. No telemetry. No account required.

---

## Built by MEDHIRA

Super-Brain is part of MEDHIRA's mission to put engineering intelligence in the hands of developers, not vendors. [About MEDHIRA →](about.md)

---

## Next steps

- [Install](install.md) — one command, then you're ready
- [Quick Start](quickstart.md) — first graph in five minutes
- [Why Super-Brain](comparison.md) — 12 concrete pain points it solves
- [CLI Reference](cli.md) — every command, every flag
- [IDE Integration](mcp.md) — one-line install for Claude, Cursor, and 12 more
- [Architecture](architecture.md) — how it all fits together
