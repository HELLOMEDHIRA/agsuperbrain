# Quick Start

Five minutes from `pip install` to answering questions about your codebase.

---

## Prerequisite

```bash
pip install agsuperbrain
```

See [Install](install.md) for alternatives (uv, from source) and system requirements.

---

## 1. Initialize — one command does it all

Inside your project directory:

```bash
agsuperbrain init
```

This single command:

1. Creates `.agsuperbrain/` with `config.yaml` and `.agsuperbrainignore`
2. Updates your `.gitignore`
3. **Runs `ingest`** on your project root — parses your code into a graph (no LLM calls, pure AST). Walks every subdirectory and automatically skips `.venv`, `node_modules`, `__pycache__`, `.git`, `dist`, `build`, and other standard noise. Works identically for flat Python, src-layout Python, Maven/Gradle/Spring Boot, Go, Rust, .NET, Rails, Flutter, Swift, Unity, Unreal, and monorepos.
4. **Runs `index-vectors`** — embeds everything for semantic search (downloads ~80 MB model on first run)
5. **Starts the background watcher** — subsequent edits are auto-indexed

By the time `init` finishes, your graph is live and ready to query.

### Overriding the defaults

```bash
agsuperbrain init --src ./services/api     # ingest one workspace (monorepos)
agsuperbrain init --skip-ingest            # config + watcher only, ingest later
```

Add custom exclusions (e.g., `generated/`, `vendor/`) to `.agsuperbrainignore` or `.gitignore`.

---

## 2. Wire it into your IDE

Pick the tool you use:

```bash
agsuperbrain claude-install          # Claude Code
agsuperbrain cursor-install          # Cursor
agsuperbrain aider-install           # Aider
agsuperbrain copilot-install         # GitHub Copilot CLI
agsuperbrain vscode-install          # VS Code Copilot Chat
agsuperbrain codex-install           # Codex
agsuperbrain gemini-install          # Gemini CLI
```

Or wire up all 14 supported tools at once:

```bash
agsuperbrain install --platform all
```

[Full IDE matrix with uninstall commands →](mcp.md)

---

## 3. Ask questions

### From the CLI

```bash
agsuperbrain ask "how does the auth flow work?"
```

Super-Brain returns the answer plus evidence — the exact functions, source files, and line numbers it used.

The `--llm` flag enables the bundled local LLM (Llama-3.2-1B) for richer phrasing. Without it, you get deterministic evidence directly.

### Semantic search

```bash
agsuperbrain search-vectors "payment processing"
```

Ranks functions and documents by semantic similarity to your query.

### Raw graph queries (power users)

```bash
agsuperbrain query "MATCH (f:Function)-[:CALLS]->(g:Function) WHERE f.name = 'handle_request' RETURN g.qualified_name"
```

Any Cypher query your KùzuDB supports.

---

## 4. (Optional) Visualize the graph

```bash
agsuperbrain visualize output/graph.html
```

Opens an interactive Cytoscape.js graph in your browser. Click nodes to navigate, drag to rearrange, zoom into subsystems.

---

## 5. (Optional) Ingest docs and audio

Super-Brain is multimodal:

```bash
agsuperbrain ingest-doc ./design-docs    # PDFs, DOCX, PPTX, MD
agsuperbrain ingest-audio ./meetings     # MP3, WAV, MP4, or a YouTube URL
```

All go into the same graph and get linked to related code via keyword overlap. Ask *"what meeting decided we'd use Postgres?"* and the graph returns the transcript segment plus the PRs that followed.

---

## Where the data lives

| Data | Path |
|---|---|
| Graph | `./.agsuperbrain/graph/` |
| Vectors | `./.agsuperbrain/qdrant/` |
| Config | `./.agsuperbrain/config.yaml` |

Everything is local. Nothing ever leaves your machine. One `agsuperbrain clean` wipes the lot.

---

## Keeping it fresh

The background watcher started by `init` picks up file changes automatically. You don't need to re-ingest manually.

### Index freshness (debounce + visibility)

- **Asynchronous indexing**: changes are queued and applied in batches.
- **Debounce + max-wait**: by default Super-Brain waits for edits to settle (\(400\) ms), but will **force a flush within \(2\) seconds** even during continuous writes (formatters / agents).
- **Verify status**: `agsuperbrain watch-status` (or inspect `./.agsuperbrain/watcher.status.json`) shows `state`, `pending_count`, `last_flush_at`, and `last_error`.

If you prefer manual control:

```bash
agsuperbrain watch ./src           # continuous watch in foreground
agsuperbrain watch ./src --once    # single pass
```

---

## Pausing or wiping

```bash
agsuperbrain stop                  # pauses the watcher, keeps all data
agsuperbrain clean                 # stops watcher, deletes .agsuperbrain/
agsuperbrain clean --yes           # same, no confirmation
```

`stop` is idempotent — running it when nothing is running is a no-op. `clean` always prompts unless `--yes` is passed, and it calls `stop` first so the watcher can't re-create files mid-delete.

---

## What next?

- [Why Super-Brain](comparison.md) — 12 concrete advantages over Claude Code / Codex / Cursor alone
- [CLI Reference](cli.md) — every command, every flag
- [IDE Integration](mcp.md) — full matrix of 14 supported tools
- [Architecture](architecture.md) — how the graph and vector store work together
