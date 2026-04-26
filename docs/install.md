# Installation

Super-Brain runs entirely on your machine. One package, one command, no accounts.

---

## Requirements

### Python version — check this first

| Version | Status |
|---|---|
| Python 3.11 | ✅ Supported |
| Python 3.12 | ✅ Supported (recommended) |
| Python 3.13 | ✅ Supported |
| Python 3.14 | ❌ **Not yet supported** — key native dependencies (tree-sitter-language-pack, llama-cpp-python, kuzu) do not yet ship wheels for 3.14. Install will fall back to source builds and fail. |
| Python ≤ 3.10 | ❌ Not supported — `agsuperbrain` requires 3.11+ features. |

Verify your interpreter:

```bash
python --version
```

If you need to install or switch versions, we recommend [`uv`](https://docs.astral.sh/uv/):

```bash
uv python install 3.12
uv venv --python 3.12
```

### Windows — native build tools (mandatory)

Several of Super-Brain's dependencies ship compiled C/C++ extensions. Pre-built wheels are available for mainstream Python versions, but if your platform/version combination lacks a wheel, pip falls back to building from source. On Windows this requires:

**Visual Studio Build Tools 2022** with the **"Desktop development with C++"** workload.

Install with:

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools
```

Or download the installer from [visualstudio.microsoft.com/downloads/](https://visualstudio.microsoft.com/downloads/) → scroll to "Tools for Visual Studio" → "Build Tools for Visual Studio 2022" → in the installer, select **Desktop development with C++**.

**Symptoms you forgot this:** `pip install` fails with `error: Microsoft Visual C++ 14.0 or greater is required` or `error: command 'cl.exe' failed`.

macOS and Linux users generally don't need extra toolchain installs — Apple's Command Line Tools and standard `gcc`/`clang` cover the native builds.

### Operating system

- **macOS** 12+
- **Linux** (Ubuntu 22.04+, Debian 12+, Fedora 38+, Arch)
- **Windows** 10/11 (native or WSL2; WSL2 avoids the Build Tools requirement since it's a Linux userspace)

### Disk space

- **Minimum**: 500 MB (code graph only, no LLM)
- **Recommended**: 5 GB (includes embedding model cache)
- **With local LLM**: 8 GB (adds ~700 MB for Llama-3.2-1B on first use)

### Optional — FFmpeg (only if you ingest audio/video)

| OS | Command |
|---|---|
| macOS | `brew install ffmpeg` |
| Ubuntu / Debian | `sudo apt install ffmpeg` |
| Fedora | `sudo dnf install ffmpeg` |
| Arch | `sudo pacman -S ffmpeg` |
| Windows | `winget install ffmpeg` or `choco install ffmpeg` |

FFmpeg is **only** required by `agsuperbrain ingest-audio`. Skip it if you're only ingesting code or documents.

---

## Install Super-Brain

### Option 1: pip

```bash
pip install agsuperbrain
```

### Option 2: uv (recommended)

```bash
uv add agsuperbrain
```

uv is faster, resolves dependencies correctly on the first try, and manages Python versions.

### Option 3: From source

```bash
git clone https://github.com/HELLOMEDHIRA/agsuperbrain.git
cd agsuperbrain
pip install -e .
```

Use this if you want to follow `main` or contribute.

---

## Verify the install

```bash
agsuperbrain doctor
```

Read-only health check — reports dependency state, data state, and watcher state without creating files or downloading models. If anything required is missing, `doctor` suggests:

```bash
agsuperbrain repair
```

One command that installs every missing declared dependency into the current Python env. `init` also calls this check automatically and offers to run `repair` for you on first setup.

---

## First-run setup

Inside any project directory:

```bash
agsuperbrain init
```

`init` does four things in one pass:

1. Writes `.agsuperbrain/config.yaml`, `.agsuperbrainignore`, and updates your `.gitignore`.
2. Runs `ingest` + `index-vectors` on your project. The extractor recursively walks from the project root and automatically skips `.venv`, `node_modules`, `__pycache__`, `.git`, `dist`, `build`, `.tox`, and other standard noise — so it works the same for flat Python, src-layout Python, Maven/Gradle/Spring Boot (`src/main/java/…`), Go (`cmd/`, `internal/`, `pkg/`), Rust crates, .NET solutions, Rails, Flutter (`lib/`), Swift (`Sources/`), Unity, Unreal, and monorepos.
3. Starts the background file watcher so subsequent edits are incrementally re-indexed.

### Overriding the defaults

```bash
agsuperbrain init --src ./services/api     # ingest just one workspace (monorepos)
agsuperbrain init --skip-ingest            # only create config + start watcher
```

Add custom exclusions to `.agsuperbrainignore` or `.gitignore` if you want to skip additional directories (e.g., `generated/`, `vendor/`, `third_party/`).

---

## Default paths

Super-Brain stores everything inside a single hidden directory:

| Data | Default path | Configurable |
|---|---|---|
| Graph database (KùzuDB) | `./.agsuperbrain/graph/` | `graph.db_path` |
| Vector store (Qdrant) | `./.agsuperbrain/qdrant/` | `vector.db_path` |
| Audio cache | `./.agsuperbrain/audio/` | — |
| Config | `./.agsuperbrain/config.yaml` | — |

`init` adds `.agsuperbrain/` to your `.gitignore` so nothing gets committed.

---

## Configuration

Edit `.agsuperbrain/config.yaml` in your project:

```yaml
# Directories to exclude from ingestion (merged with defaults like .venv, node_modules)
exclude:
  - third_party
  - generated

# Languages to prioritize (leave empty for all 306)
languages:
  - python
  - typescript
  - go

# Watcher settings
watcher:
  debounce_ms: 500

# Storage
graph:
  db_path: ./.agsuperbrain/graph

vector:
  db_path: ./.agsuperbrain/qdrant
```

Changes apply on the next `agsuperbrain` command — no restart needed.

---

## Pause or uninstall

To pause indexing without losing any data:

```bash
agsuperbrain stop                 # stops the background watcher
```

To wipe all Super-Brain data for a project (prompts for confirmation):

```bash
agsuperbrain clean                # stops watcher, removes .agsuperbrain/
agsuperbrain clean --yes          # no confirmation (for scripts)
```

To uninstall the package itself:

```bash
pip uninstall agsuperbrain        # or: uv remove agsuperbrain
```

---

## Troubleshooting

### `agsuperbrain: command not found`

Make sure pip's script directory is on your `PATH`:

```bash
# macOS / Linux
export PATH="$HOME/.local/bin:$PATH"
```

On Windows:

```powershell
setx PATH "%PATH%;%APPDATA%\Python\Scripts"
```

Open a new terminal after changing `PATH`.

### `ModuleNotFoundError: No module named 'agsuperbrain'`

Your virtual environment probably isn't active.

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

### `Ingest skipped — missing runtime dependency: No module named 'tree_sitter_language_pack'` (or similar)

One-command fix:

```bash
agsuperbrain repair
```

This installs every declared dependency that's missing from your current Python env. It uses `sys.executable -m pip install`, so the packages land in the exact interpreter running the CLI — no env-mismatch risk.

If `repair` itself reports failure, the underlying cause is one of:

1. **Python 3.14**: wheels don't exist yet. Downgrade to 3.11, 3.12, or 3.13.
2. **Windows without Build Tools**: install Visual Studio Build Tools 2022 with the "Desktop development with C++" workload (see the Requirements section above), then re-run `agsuperbrain repair`.
3. **Network / PyPI outage**: retry after a minute.

Diagnose with:

```bash
agsuperbrain doctor
pip show agsuperbrain tree-sitter-language-pack
```

### `error: Microsoft Visual C++ 14.0 or greater is required` (Windows)

Install Visual Studio Build Tools 2022 with the "Desktop development with C++" workload:

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools
```

Then reinstall Super-Brain.

### FFmpeg not found

Install it per the OS table above and open a new terminal so the updated `PATH` takes effect.

### KùzuDB / Qdrant errors on first run

Run `agsuperbrain clean` then `agsuperbrain init` to rebuild. This is usually a sign that a previous run was interrupted mid-write.

### Slow first query

The sentence-transformer model downloads on first use (~80 MB). Subsequent queries are instant.

---

## Next steps

- [Quick Start](quickstart.md) — build your first graph in five minutes
- [CLI Reference](cli.md) — every command explained
- [IDE Integration](mcp.md) — wire Super-Brain into your editor
