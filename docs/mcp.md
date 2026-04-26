# IDE Integration

Super-Brain plugs into **14 AI coding tools**. Each has a one-command installer that drops the right files in the right places — no manual JSON editing required.

---

## What integration looks like

Super-Brain uses one of three integration styles depending on what the target tool supports:

| Style | Example | How it works |
|---|---|---|
| **MCP server** | Aider, Claude Code, Gemini | Tool calls Super-Brain over stdio JSON-RPC at query time |
| **Hook** | Claude Code, Gemini CLI | Pre-tool hook injects Super-Brain context before the assistant runs file searches |
| **Rules / skills** | Copilot, Kiro, Hermes, … | A markdown rule file the assistant reads on every request |
| **MCP + rules** | Cursor, Aider, … | stdio tools plus a rule/AGENTS file (see the platform matrix) |

Most installers use a combination — Claude Code gets a hook **and** a rule file; Aider gets MCP **and** an `AGENTS.md`; Cursor gets **MCP +** a project rule (`.cursor/rules/`) when you use `agsuperbrain cursor-install`.

---

## One-command install

### All at once

```bash
agsuperbrain install --platform all
```

### Per platform

```bash
agsuperbrain claude-install           # Claude Code
agsuperbrain cursor-install           # Cursor
agsuperbrain aider-install            # Aider
agsuperbrain codex-install            # Codex
agsuperbrain opencode-install         # OpenCode
agsuperbrain copilot-install          # GitHub Copilot CLI
agsuperbrain vscode-install           # VS Code Copilot Chat
agsuperbrain gemini-install           # Gemini CLI
agsuperbrain hermes-install           # Hermes
agsuperbrain kiro-install             # Kiro
agsuperbrain antigravity-install      # Google Antigravity
agsuperbrain openclaw-install         # OpenClaw
agsuperbrain droid-install            # Factory Droid
agsuperbrain trae-install             # Trae / Trae CN
```

**Before running any of these**, finish the one-time setup:

```bash
agsuperbrain init
agsuperbrain ingest ./src
agsuperbrain index-vectors
```

The graph needs to exist before your assistant can query it.

---

## Platform matrix

| Platform | Install command | MCP server auto-registered? | Files created | Integration style |
|---|---|---|---|---|
| Claude Code | `claude-install` | ✅ yes | `.claude/settings.json`, `CLAUDE.md`, `AGENTS.md` | MCP + PreToolUse hook + rules |
| Cursor | `cursor-install` | ✅ yes | `.cursor/mcp.json`, `.cursor/rules/superbrain.mdc` | MCP + always-on rule file |
| Aider | `aider-install` | ✅ yes | `.aider.conf.yml`, `AGENTS.md` | MCP + rules |
| Gemini CLI | `gemini-install` | ✅ yes | `.gemini/settings.json`, `AGENTS.md` | MCP + BeforeTool hook + rules |
| Codex | `codex-install` | ❌ rules only | `AGENTS.md` | Rule file |
| OpenCode | `opencode-install` | ❌ rules only | `AGENTS.md` | Rule file |
| GitHub Copilot CLI | `copilot-install` | ❌ skill only | `~/.copilot/skills/superbrain/SKILL.md` | Global skill |
| VS Code Copilot Chat | `vscode-install` | ❌ rules only | `.github/copilot-instructions.md` | Repo instructions |
| Hermes | `hermes-install` | ❌ skill only | `~/.hermes/skills/superbrain/SKILL.md`, `AGENTS.md` | Global skill + rules |
| Kiro | `kiro-install` | ❌ skill only | `.kiro/skills/superbrain/SKILL.md`, `.kiro/steering/superbrain.md` | Skill + steering |
| Google Antigravity | `antigravity-install` | ❌ rules only | `.agent/rules/superbrain.md`, `.agent/workflows/superbrain.md` | Rules + workflows |
| OpenClaw | `openclaw-install` | ❌ rules only | `AGENTS.md` | Rule file |
| Factory Droid | `droid-install` | ❌ rules only | `AGENTS.md` | Rule file |
| Trae / Trae CN | `trae-install` | ❌ rules only | `AGENTS.md` | Rule file |

**What "MCP auto-registered" means.** For the four tools in the top half of the table, the installer writes a `mcpServers` entry pointing at `sys.executable -m agsuperbrain mcp` (or `mcp-serve` — same command). Your assistant can then *call* Super-Brain's tools (`search_code`, `find_callers`, `path_between`, …) directly — not just read rule text about them. Using `python -m` instead of the `agsuperbrain` script name bypasses PATH issues that often affect **Cursor and other IDEs** on Windows/macOS, where the GUI process may not see your venv’s `Scripts/` on `PATH`.

To print the exact JSON for *this* machine, run: `agsuperbrain print-mcp-config` (then merge the `mcpServers.agsuperbrain` object into your existing `mcp.json` if you already have other servers).

For the other tools, their native integration primitive is a rule file or skill file, not MCP — so the installer writes the format that tool actually understands. If you want MCP with one of them too, set it up manually (see "Manual MCP configuration" below); it's additive to whatever the installer wrote.

All install commands are idempotent — run them twice and nothing breaks.

---

## Uninstall

Dedicated uninstallers exist for the three tools whose integration changes shared settings files:

```bash
agsuperbrain claude-uninstall      # removes hooks from .claude/settings.json
agsuperbrain cursor-uninstall      # removes .cursor/rules/superbrain.mdc
agsuperbrain aider-uninstall       # unpatches .aider.conf.yml
```

For the other platforms, installation is additive and non-destructive — just delete the file(s) listed in the matrix above.

---

## MCP: what your assistant can do

When the MCP server runs (started automatically by the Aider, Claude Code, and Gemini integrations, or manually via `agsuperbrain mcp-serve`), these tools become available:

| Tool | Purpose |
|---|---|
| `search_code` | Semantic search across code and documents |
| `find_callers` | All functions that call a given function |
| `find_callees` | All functions a given function calls |
| `get_function_body` | Full source, docstring, and signature of a function |
| `path_between` | Call path from one function to another |
| `closure` | Transitive closure of any relationship |
| `get_subgraph` | Local neighborhood around a node |
| `stats` | Counts per node/edge type |
| `list_modules` | Every module in the graph |
| `list_functions` | Every function in the graph, optionally filtered by module |
| `watcher_status` | Read watcher freshness (pending/idle, last flush, last error) |
| `await_index_idle` | Wait until watcher is idle before querying (prevents stale reads after edits) |

These are called by your assistant, not by you — but if you're debugging, `agsuperbrain mcp-serve` lets you test them manually.

---

## Index freshness for agent calls

Super-Brain indexing is asynchronous: file edits are queued and applied in batches (debounce + max-wait). To avoid stale answers when the user or an agent just modified files:

- Every MCP tool response includes an **`index_state`** block (mirrors `./.agsuperbrain/watcher.status.json`).
- Agents can call **`await_index_idle`** before any query when they need the most up-to-date graph/vectors.

---

## Using Super-Brain from agent frameworks

Super-Brain's MCP server works with **any framework that speaks MCP**:

- LangChain / LangGraph (via `langchain-mcp-adapters`)
- AutoGen (native MCP)
- CrewAI (MCP tool connector)
- SmolAgents
- Plain stdio JSON-RPC

### LangChain / LangGraph

```python
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_agent
from langchain_mcp_adapters.tools import load_mcp_server

mcp = load_mcp_server(command="agsuperbrain", args=["mcp-serve"])
tools = mcp.get_tools()

llm = ChatOpenAI(model="gpt-4o")
agent = create_agent(llm, tools, prompt="You are a codebase expert.")

response = agent.invoke({"messages": ["How does authentication work?"]})
```

### AutoGen

```python
from autogen import ConversableAgent

agent = ConversableAgent(
    name="code_expert",
    llm_config={"model": "gpt-4o"},
    tools=[{"command": "agsuperbrain", "args": ["mcp-serve"]}],
)
```

### CrewAI

```python
from crewai import Agent
from crewai.tools import MCPTool

code_tools = MCPTool(
    server_name="agsuperbrain",
    server_command="agsuperbrain mcp-serve",
)
expert = Agent(tools=[code_tools], role="Codebase Expert")
```

---

## Manual MCP configuration (advanced)

If you prefer to wire the MCP server yourself instead of using an `<ide>-install` command, here are the configs:

### Claude Code — `~/.claude/settings.json`

```json
{
  "mcpServers": {
    "superbrain": {
      "command": "agsuperbrain",
      "args": ["mcp-serve"]
    }
  }
}
```

### Cursor — `%USERPROFILE%\.cursor\mcp.json` (global) or `<repo>\.cursor\mcp.json` (project)

Cursor loads **both** a user-level config and a project-level `.cursor/mcp.json` when that folder is open. The `cursor-install` command writes the **project** file only.

**Prefer this** (works even when `agsuperbrain` is not on the IDE’s `PATH`, which is the usual reason MCP “does not load” on Windows after `pip install` into a venv):

```json
{
  "mcpServers": {
    "agsuperbrain": {
      "type": "stdio",
      "command": "C:\\Path\\To\\python.exe",
      "args": ["-u", "-m", "agsuperbrain", "mcp"]
    }
  }
}
```

Replace `command` with the output of `where python` (Windows) or `which python` (Unix) for the same environment where you installed `agsuperbrain`, or run `agsuperbrain print-mcp-config` and paste the result.

Relying on the bare `agsuperbrain` launcher often fails in Cursor because the IDE was not started from an activated venv, so the launcher is not on `PATH`.

`cursor-install` also writes `.cursor/rules/superbrain.mdc` for always-on instructions — that is separate from registering the MCP server.

### Aider — `.aider.conf.yml`

```yaml
mcp-server: agsuperbrain:mcp-serve
```

### Custom DB paths

Any MCP client can be configured to use a custom graph or vector path:

```json
{
  "mcpServers": {
    "superbrain": {
      "command": "agsuperbrain",
      "args": [
        "mcp-serve",
        "--db", "/path/to/graph",
        "--qdrant-path", "/path/to/qdrant"
      ]
    }
  }
}
```

---

## Troubleshooting

### The assistant doesn't see Super-Brain's tools

1. Run `agsuperbrain doctor` and confirm every component is green.
2. Confirm you've run `agsuperbrain ingest ./src` — the graph must exist.
3. Restart your IDE — MCP servers are loaded at IDE startup.
4. Check the IDE's MCP logs. In Cursor: **Settings → Tools & MCP** and the entry for `agsuperbrain` (red/error text); or **Help → Toggle Developer Tools → Console**.
5. **Cursor:** if tools never appear, run `agsuperbrain print-mcp-config` from the venv where you installed the package, then merge that `mcpServers.agsuperbrain` block into `%USERPROFILE%\.cursor\mcp.json` *or* your project’s `.cursor/mcp.json`. A single bad JSON or invalid server entry in `mcp.json` can prevent servers from loading — validate the file and fix any other broken entries.

### "Connection refused" or "server failed to start"

- Make sure `agsuperbrain` is on your `PATH` (`which agsuperbrain` / `where agsuperbrain` should print a path).
- MCP uses stdio — nothing is listening on a network port, so firewall rules aren't the cause.

### The assistant answers but without Super-Brain context

Re-run the install command for that platform. Integration files may have been overwritten by an update to the IDE or a linter.

### MCP `stats` / `list_functions` do not match the current repo, or `search_code` is stale

Super-Brain keeps two stores:

- **Kùzu (graph)** — `stats`, `find_*`, `get_function_body`, `path_between`, etc. These reflect the last **ingest** or **watcher** run.
- **Qdrant (vectors)** — powers **`search_code`** and semantic / hybrid search over embeddings.

The **file watcher** re-ingests into **Kùzu** when you save, then does an **incremental** Qdrant update: it **does not** re-embed the whole project — only nodes whose `source_path` matches the files that changed (small constant-size work per save, not O(repo size) for the embedding pass). You still need a **one-time** `agsuperbrain index-vectors` on a new project (or the initial index from `init`) so the Qdrant collection exists. For a full rebuild of *all* embeddings, or to repair a broken collection, run:

`agsuperbrain index-vectors`

(omit `--incremental` for a from-scratch reindex. `index-vectors --incremental` is mainly for the CLI; the watcher’s path-targeted reindex is usually enough for day-to-day edits.)

**Also check** the MCP (and terminal) are using the same project **cwd** and `.agsuperbrain/` as the `ingest` you care about; different folders mean different data.

---

## Next steps

- [CLI Reference](cli.md) — the commands behind every integration
- [Architecture](architecture.md) — what the MCP tools actually query
- [Why Super-Brain](comparison.md) — the problems this integration solves
