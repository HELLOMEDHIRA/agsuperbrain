# CLI Reference

Complete command reference for `agsuperbrain`. Every command below is verified against the current codebase.

Run `agsuperbrain --help` for the live list, or `agsuperbrain <command> --help` for a single command's flags.

---

## Command map

| Category | Commands |
|---|---|
| Setup | `init`, `doctor`, `repair` |
| Ingestion | `ingest`, `ingest-doc`, `ingest-audio` |
| Indexing | `index-vectors`, `link` |
| Querying | `ask`, `search-vectors`, `query`, `inspect-function` |
| Analysis | `stats`, `report`, `cluster`, `visualize` |
| Lifecycle | `watch`, `watch-status`, `stop`, `clean`, `export`, `import` |
| MCP / IDE | `mcp-serve`, `print-mcp-config`, `install`, `<ide>-install`, `<ide>-uninstall` |

---

## Setup

### `init`

Initialize Super-Brain in the current project — one command does everything.

```bash
agsuperbrain init
agsuperbrain init --path ./my-project
agsuperbrain init --src ./apps/backend     # explicit source directory
agsuperbrain init --skip-ingest            # config only; ingest later
```

Performs, in order:

1. Writes `.agsuperbrain/config.yaml`, `.agsuperbrainignore`, and updates `.gitignore` and `.claude/settings.json`.
2. Runs `ingest` on your project root. The extractor walks every subdirectory and automatically skips `.venv`, `node_modules`, `__pycache__`, `.git`, `dist`, `build`, `.tox`, and other standard noise — so one command works for flat Python, src-layout Python, Maven/Gradle/Spring Boot (`src/main/java/…`), Go (`cmd/`, `internal/`, `pkg/`), Rust crates, .NET solutions, Rails, Flutter (`lib/`), Swift (`Sources/`), Unity, Unreal, and monorepos. Override with `--src <path>` to target a specific workspace. Skip entirely with `--skip-ingest`.
3. Runs `index-vectors` for semantic search (downloads an ~80 MB embedding model on first run).
4. Starts the background file watcher so subsequent edits are incrementally re-indexed.

By the time `init` finishes, your graph is populated and your watcher is live.

If any runtime dependency is missing, `init` detects it and prompts you to run `repair` — no manual `pip install` commands to copy.

### `doctor`

Read-only health check. Never creates files, starts processes, or downloads models.

```bash
agsuperbrain doctor
```

Reports:

- **Runtime dependencies** — which declared deps are importable; for missing required deps, shows the exact `pip install X` command.
- **Optional features** — FFmpeg (audio ingestion), `llama-cpp-python` (LLM answers), `faster-whisper` (transcription). Missing optionals are warnings, not failures.
- **Data state** — function count in the graph, vector count in Qdrant. Distinguishes "not initialized" from "initialized but empty" from "populated".
- **Watcher state** — running (with PID), not running, or stale PID.

Exits non-zero only on real failures. Empty graph / missing collection are reported as warnings, which is the normal pre-ingest state.

If the watcher is running, `doctor` may report graph/vector stores as "in use by watcher" (warnings), because Kùzu and Qdrant local-mode use single-writer locks.

If any dependency is missing, the footer points at [`agsuperbrain repair`](#repair) as the one-command fix.

### `repair`

Install any missing declared runtime dependencies into the current Python environment.

```bash
agsuperbrain repair                       # prompts before installing
agsuperbrain repair --yes                 # non-interactive (CI / scripts)
agsuperbrain repair --include-optional    # also install llama-cpp-python, faster-whisper
```

Uses `sys.executable -m pip install -U` — the exact same Python interpreter that's running the CLI — so the installed packages are guaranteed available to subsequent `agsuperbrain` commands. No "installed into the wrong env" confusion.

Shows the exact pip command before running it. Re-verifies after the install and reports any deps that `pip` claimed to install but still aren't importable (typically a platform/version wheel gap).

If the pip install itself fails, `repair` prints the most common fixes:

- **Windows**: install Visual Studio Build Tools 2022 (Desktop C++ workload)
- **Python 3.14**: not supported — use 3.11, 3.12, or 3.13
- Run `agsuperbrain doctor` for per-component diagnosis

---

## Ingestion

### `ingest`

Parse source code into the graph.

```bash
agsuperbrain ingest ./src
agsuperbrain ingest ./src ./lib ./services
```

Walks every directory argument, picks files whose language tree-sitter supports, extracts functions/methods/classes and their call relationships, writes them to the graph. Pure AST — no LLM calls.

### `ingest-doc`

Ingest documents (PDF, DOCX, PPTX, MD, TXT, HTML).

```bash
agsuperbrain ingest-doc ./design-docs
agsuperbrain ingest-doc ./README.md ./ARCHITECTURE.md
```

Extracts sections, headings, and concepts; each becomes a graph node linked to its document.

### `ingest-audio`

Transcribe and ingest audio or video.

```bash
agsuperbrain ingest-audio ./meetings/standup.mp3
agsuperbrain ingest-audio https://youtube.com/watch?v=xxxx
```

Accepts local files (MP3, WAV, MP4, etc.) or YouTube URLs. Uses local faster-whisper — nothing is uploaded. Segments become graph nodes with timestamps.

Requires FFmpeg on your `PATH`.

---

## Indexing

### `index-vectors`

Embed every function, document section, and transcript segment into the vector store for semantic search.

```bash
agsuperbrain index-vectors
```

Uses a local sentence-transformer model (~80 MB, downloaded on first run). Incremental on subsequent runs — only new/changed nodes are re-embedded.

### `link`

Build cross-modal links between code, documents, and audio via keyword overlap.

```bash
agsuperbrain link
```

Run this after any combination of `ingest`, `ingest-doc`, `ingest-audio` to connect related content across modalities.

---

## Querying

### `ask`

Natural-language question with deterministic evidence.

```bash
agsuperbrain ask "how does DataProcessor initialize?"
agsuperbrain ask "what validates JWT tokens?" --llm
```

Flags:

- `--llm` — use the local LLM to phrase the answer. Without it, you get evidence directly.
- `--db <path>` — override the graph DB path.

Returns the answer, the nodes used as evidence (score, hops, source file, line number), and the confidence score.

### `search-vectors`

Pure semantic search over the vector index.

```bash
agsuperbrain search-vectors "payment processing"
agsuperbrain search-vectors "error handling" --limit 10
```

Ranks all embedded nodes by cosine similarity.

### `query`

Raw Cypher query against the graph.

```bash
agsuperbrain query "MATCH (f:Function) RETURN f.qualified_name LIMIT 10"
agsuperbrain query "MATCH (f:Function)-[:CALLS]->(g:Function) WHERE f.name='main' RETURN g.qualified_name"
```

For advanced users who want to ask questions the high-level commands don't cover.

### `inspect-function`

Show a function's full body, docstring, callers, and callees.

```bash
agsuperbrain inspect-function DataProcessor.process
agsuperbrain inspect-function main
```

Accepts either a qualified name (`ClassName.method`) or a bare name (returns the first match).

---

## Analysis

### `stats`

Quick statistics about the graph.

```bash
agsuperbrain stats
```

Counts per node type (Module, Function, Class, Document, Section, Concept, Audio, Transcript, etc.) and per edge type.

### `report`

Generate `GRAPH_REPORT.md` with god-nodes, cross-module dependencies, orphan modules, and suggested follow-up questions.

```bash
agsuperbrain report
```

Writes to the project root on demand. Useful for onboarding a new teammate or auditing architecture drift.

**Note:** `init` and the background watcher also generate `.agsuperbrain/GRAPH_REPORT.md` and `.agsuperbrain/graph.html` automatically after every re-index, so most users never need to run `report` manually.

### `cluster`

Run Leiden community detection on the call graph.

```bash
agsuperbrain cluster
```

Groups functions into subsystems without any manual tagging. Results stored in the graph and visible via `visualize`.

### `visualize`

Generate an interactive Cytoscape.js visualization.

```bash
agsuperbrain visualize output/graph.html
agsuperbrain visualize output/graph.html --root DataProcessor.process --depth 2
```

Open the output HTML in any browser. Click nodes to navigate, drag to rearrange.

---

## Lifecycle

### `watch`

Foreground file watcher for manual control (the one started by `init` runs in the background).

```bash
agsuperbrain watch ./src           # continuous
agsuperbrain watch ./src --once    # single pass then exit
```

Changes are detected by content hash, re-indexed incrementally, and deleted files are swept from the graph.

Notes:

- **Default path**: `agsuperbrain watch` watches `.` (the current directory).
- **Debounce + max-wait**: `--debounce` waits for edits to settle; `--max-wait` forces a flush during continuous writes (agents/formatters). Both default from `.agsuperbrain/config.yaml`.

### `watch-status`

Show watcher freshness and pending queue (useful when the watcher runs in background).

```bash
agsuperbrain watch-status
agsuperbrain watch-status --path ./my-project
```

### `stop`

Stop the background watcher without deleting any data.

```bash
agsuperbrain stop
agsuperbrain stop --path ./my-project
```

Use this when you want indexing to pause — for example, before running a large rebase, a CI job, or just to free the file handle. Your graph, vectors, and config are all preserved. Re-run `agsuperbrain init` (or any ingest command) to resume.

### `clean`

Stop the watcher and wipe **all** Super-Brain data for this project.

```bash
agsuperbrain clean
agsuperbrain clean --yes      # skip confirmation
agsuperbrain clean --path ./my-project
```

Removes the entire `.agsuperbrain/` directory — graph, vector store, audio cache, config, PID file. Confirms before deleting unless `--yes` is passed. Your source code is never touched.

`clean` automatically calls `stop` first so the watcher can't re-create files mid-delete.

### `export`

Dump the graph to a JSON file for backup or transfer.

```bash
agsuperbrain export ./backup.json
```

### `import`

Load a graph from a JSON dump.

```bash
agsuperbrain import ./backup.json
```

Use together with `export` to move a graph between machines or snapshot a known-good state.

---

## MCP / IDE integration

### `mcp-serve`

Start the MCP server over stdio JSON-RPC.

```bash
agsuperbrain mcp-serve
```

Exposes ten tools to any MCP-compatible client: `search_code`, `find_callers`, `find_callees`, `get_function_body`, `path_between`, `closure`, `get_subgraph`, `stats`, `list_modules`, `list_functions`.

Most users don't run this manually — the `<ide>-install` commands wire it up for you.

### `print-mcp-config`

Prints a full `mcp.json` object for the **current** Python (`sys.executable` — the same venv you run the command from). Use it when an IDE can’t see `agsuperbrain` on `PATH` (typical for Cursor on Windows) and you need a paste-ready `mcpServers.agsuperbrain` block.

```bash
agsuperbrain print-mcp-config
agsuperbrain print-mcp-config --ide claude
```

### `install`

Install Super-Brain integration for a specific platform or all of them.

```bash
agsuperbrain install --platform all
agsuperbrain install --platform claude
agsuperbrain install --platform cursor
```

Accepts: `all`, `claude`, `cursor`, `aider`, `codex`, `opencode`, `vscode`, `openclaw`, `droid`, `trae`, `gemini`, `hermes`, `kiro`, `antigravity`, `copilot`.

### Per-platform install / uninstall

Each supported IDE has its own dedicated command:

```bash
agsuperbrain claude-install           agsuperbrain claude-uninstall
agsuperbrain cursor-install           agsuperbrain cursor-uninstall
agsuperbrain aider-install            agsuperbrain aider-uninstall
agsuperbrain codex-install
agsuperbrain opencode-install
agsuperbrain copilot-install
agsuperbrain vscode-install
agsuperbrain gemini-install
agsuperbrain hermes-install
agsuperbrain kiro-install
agsuperbrain antigravity-install
agsuperbrain openclaw-install
agsuperbrain droid-install
agsuperbrain trae-install
```

Uninstall commands exist for Claude, Cursor, and Aider today. For other platforms, integration is additive and non-destructive — remove the installed files manually (see [IDE Integration](mcp.md) for exact file paths).

---

## Global flags

Most commands accept:

| Flag | Purpose | Default |
|---|---|---|
| `--db <path>` | Override graph DB path | `./.agsuperbrain/graph` |
| `--path <path>` | Override project path (install commands) | `.` |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Error (details printed to stderr) |
| `2` | Bad CLI arguments |

---

## Next steps

- [IDE Integration](mcp.md) — detailed per-platform setup
- [Architecture](architecture.md) — what happens under the hood
