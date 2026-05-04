# Super-Brain

<p align="center">
  <a href="https://pypi.org/project/agsuperbrain">
    <img src="https://img.shields.io/pypi/v/agsuperbrain?style=flat&color=007ec6" alt="PyPI">
  </a>
  <a href="https://pypi.org/project/agsuperbrain">
    <img src="https://img.shields.io/pypi/dm/agsuperbrain?style=flat" alt="Downloads">
  </a>
  <a href="https://github.com/HELLOMEDHIRA/agsuperbrain/blob/main/LICENSE">
    <img src="https://img.shields.io/pypi/l/agsuperbrain?style=flat" alt="License">
  </a>
  <a href="https://python.org">
    <img src="https://img.shields.io/pypi/pyversions/agsuperbrain?style=flat" alt="Python">
  </a>
  <a href="https://agsuperbrain.readthedocs.io">
    <img src="https://img.shields.io/readthedocs/agsuperbrain?style=flat" alt="Docs">
  </a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/HELLOMEDHIRA/medhira/main/assets/medhira-logo.png" alt="MEDHIRA" width="100"/>
</p>

<p align="center">
  <strong>Your codebase's working memory — local, fast, permanent.</strong>
</p>

---

Super-Brain gives your AI coding assistant a persistent, structured understanding of your code. Instead of re-reading files every turn, your assistant queries a local knowledge graph and gets back the exact functions, call paths, and semantics it needs.

**100% local. 14 IDEs supported. Zero code uploaded.**

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

## Why Super-Brain

| Pain point | Claude Code / Codex / Cursor / Copilot alone | With Super-Brain |
|---|---|---|
| Session amnesia | Starts from zero every session | Graph persists on disk |
| Re-reading files | Every turn | One ingest, then queries |
| Exploration cost | Scales with codebase | Flat, query-shaped |
| Call graph | Grep-and-hope | Deterministic, AST-derived |
| Path reasoning | Chains of reads | `path_between` one-hop |
| Privacy | Code uploads to vendor | Nothing leaves your machine |
| Cross-repo | One project at a time | Unlimited repos, one graph |
| Docs & audio | Invisible | First-class via `ingest-doc` / `ingest-audio` |
| Hallucinated dependencies | Possible under load | Zero — AST is ground truth |
| Language coverage | Top ~20 | **306** via tree-sitter |

See the [full comparison](https://agsuperbrain.readthedocs.io/en/latest/comparison/) for 12 detailed pain points.

---

## Install

```bash
pip install agsuperbrain
```

Or with uv:

```bash
uv add agsuperbrain
```

### Before you install

- **Python 3.11, 3.12, or 3.13** — Python 3.14 is **not yet supported** (native-extension deps don't ship wheels for 3.14).
- **Windows only** — install [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/downloads/) with the "Desktop development with C++" workload. Several deps compile native code and need a C/C++ toolchain. WSL2 users can skip this.
- **FFmpeg** — required only if you plan to ingest audio/video. Skip it for code-only use.

Full prerequisites and troubleshooting: [Installation guide](https://agsuperbrain.readthedocs.io/en/latest/install/).

---

## Quick start

```bash
agsuperbrain init                     # configures + auto-ingests + indexes
agsuperbrain claude-install           # or: cursor-install, aider-install, etc.
```

The first command sets up config, auto-detects your source directory, builds the graph, embeds it for semantic search, and starts the background watcher — all in one pass. The second wires Super-Brain into your AI coding tool.

That's it. Your assistant now has permanent, structured access to your codebase.

---

## Works with 14 AI coding tools

One install command per platform:

| Tool | Command |
|---|---|
| Claude Code | `agsuperbrain claude-install` |
| Cursor | `agsuperbrain cursor-install` |
| Aider | `agsuperbrain aider-install` |
| Codex | `agsuperbrain codex-install` |
| OpenCode | `agsuperbrain opencode-install` |
| GitHub Copilot CLI | `agsuperbrain copilot-install` |
| VS Code Copilot Chat | `agsuperbrain vscode-install` |
| Gemini CLI | `agsuperbrain gemini-install` |
| Hermes | `agsuperbrain hermes-install` |
| Kiro | `agsuperbrain kiro-install` |
| Google Antigravity | `agsuperbrain antigravity-install` |
| OpenClaw | `agsuperbrain openclaw-install` |
| Factory Droid | `agsuperbrain droid-install` |
| Trae / Trae CN | `agsuperbrain trae-install` |

All at once: `agsuperbrain install --platform all`.

Also works with any MCP-speaking agent framework (LangChain, LangGraph, AutoGen, CrewAI, SmolAgents).

---

## What it gives you

- **306 language support** — Python, JS/TS, Go, Rust, Java, C/C++, Ruby, PHP, Kotlin, Swift, Scala, and 296 more via tree-sitter
- **Deterministic extraction** — call graph comes from AST, not LLM inference
- **Hybrid retrieval** — vector search for semantics + graph expansion for structure
- **Local LLM (optional)** — bundled Llama-3.2-1B for free, offline answers
- **Interactive visualization** — Cytoscape.js graph, click to navigate
- **File watcher** — code changes re-indexed automatically
- **Community detection** — Leiden clustering surfaces subsystems
- **Multimodal** — ingest PDFs, DOCX, MD, audio, and video into the same graph

---

## Measured performance

Real numbers from a self-corpus pilot (the `agsuperbrain` repository itself; 131 files, 86 Tier-1 source files, ~10.5 min cold ingest, 22.9 MiB total index). Reproducible via `paper/evaluation/run_eval.py`, `run_rq1.py`, `run_rq3.py`.

### Pilot evaluation at a glance

| RQ | Question | Pilot result | Status |
|---|---|---|---|
| RQ1 | Extraction accuracy vs. reference analyser | Precision **0.94**, Recall **0.38**, F1 **0.54** | Pilot — Python, vs. `code2flow` 2.5.1 on 247 functions |
| RQ2 | Query latency (graph + hybrid) | `find_callers` p95 = **2.5 ms**; hybrid `search_code` p95 = **781 ms** | Pilot — n=30 per primitive, single repo |
| RQ3 | Token-cost reduction vs. context-stuffing | **9.22× aggregate** (210,659 → 22,837 tokens) | Pilot — N=10 queries, 1 LLM (Llama-3.3-70B) |
| RQ4 | Language coverage (code + doc pipelines) | Python **100%** (40/40), JavaScript **100%** (36/36) per code-file | Pilot — 2 Tier-1 langs; doc pipeline on `.md`/`.html` |

### Token cost — same 10 questions, same LLM (Llama-3.3-70B on Groq)

![Token cost comparison: 210,659 vs 22,837](paper/fig5-rq3-token-comparison.png)

| Mode | Total tokens (10 questions) | Mean per question | Notes |
|---|---:|---:|---|
| **Without Super-Brain** (context-stuffing baseline) | **210,659** | 21,066 | packs as much code as fits in the context window |
| **With Super-Brain** (evidence bundle) | **22,837** | 2,284 | only the retrieved Function/Section evidence |
| **Reduction** | **9.22× less** (saves 187,822 tokens) | 9.22× | comparable answer quality (within noise) |

For the input prompt specifically the gap widens to **9.49×** (20,870 vs 2,199 tokens per question). At commodity LLM pricing this is roughly an order-of-magnitude cost reduction per developer question — and the index is built once, not per session.

### Extraction & query latency

| Metric | Result |
|---|---|
| Code extraction (Python, per code-file) | **100% (40/40)** |
| Code extraction (JavaScript, per code-file) | **100% (36/36)** |
| Document extraction (Markdown, Section coverage) | **90% (9/10)** |
| Document extraction (HTML, Section coverage) | **100% (9/9)** |
| Edge precision vs. code2flow reference (Python) | **94%** — when SB emits an edge, an independent static analyser confirms it |
| Edge recall vs. code2flow reference (Python) | **38%** — gap is method-call resolution, the next optimisation target |
| `find_callers` graph query (p50 / p95) | **2.0 / 2.5 ms** |
| `find_callees` graph query (p50 / p95) | **2.3 / 3.1 ms** |
| `closure` graph query, depth 3 (p50 / p95) | **4.3 / 7.4 ms** |
| Hybrid `search_code` (p50 / p95) | **491 / 781 ms** |
| Cold-start storage footprint | **22.9 MiB** for 5.4 MiB of source/docs |

> **Pilot scope:** single self-corpus, single LLM for the token-cost study, 10 queries with one rep each. The 9.22× ratio is measured on hand-curated developer questions answerable from the codebase; broader multi-repo, multi-LLM, multi-rep replication is the next milestone. Full caveats: [the paper](paper/super-brain.md#5-evaluation).

---

## Privacy by default

Every byte Super-Brain touches stays on your machine:

- Graph database: local KùzuDB file
- Vector store: local Qdrant directory
- Embeddings: local sentence-transformers
- LLM (optional): local llama.cpp
- Transcription: local faster-whisper

No accounts. No telemetry. No network required.

---

## Configuration

Create or edit `.agsuperbrain/config.yaml`:

```yaml
exclude:
  - .venv
  - node_modules

watcher:
  debounce_ms: 500

graph:
  db_path: ./.agsuperbrain/graph

vector:
  db_path: ./.agsuperbrain/qdrant
```

Super-Brain also honors `.gitignore` and the Super-Brain-specific `.agsuperbrainignore`.

---

## Requirements

- **Python 3.11, 3.12, or 3.13** (3.14 not yet supported — native-extension wheels unavailable)
- **Windows only:** Visual Studio Build Tools 2022 with "Desktop development with C++" workload
- ~500 MB disk (5 GB with embedding-model cache, 8 GB with local LLM)
- FFmpeg (only if you ingest audio/video)

---

## Documentation

- [Install](https://agsuperbrain.readthedocs.io/en/latest/install/)
- [Quick Start](https://agsuperbrain.readthedocs.io/en/latest/quickstart/)
- [Why Super-Brain](https://agsuperbrain.readthedocs.io/en/latest/comparison/)
- [CLI Reference](https://agsuperbrain.readthedocs.io/en/latest/cli/)
- [IDE Integration](https://agsuperbrain.readthedocs.io/en/latest/mcp/)
- [Architecture](https://agsuperbrain.readthedocs.io/en/latest/architecture/)

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).

---

## Contributing

Contributions welcome. Open an issue first for anything non-trivial so we can align on approach.

---

## Star history

[![Star History Chart](https://api.star-history.com/svg?repos=HELLOMEDHIRA/agsuperbrain&type=Date)](https://star-history.com/#HELLOMEDHIRA/agsuperbrain&Date)

---

Built by [MEDHIRA](https://medhira.readthedocs.io/en/latest/) — engineering intelligence across everything.
