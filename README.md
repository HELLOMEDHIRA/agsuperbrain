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
