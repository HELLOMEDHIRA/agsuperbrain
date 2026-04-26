"""cli.py — Typer CLI entry point (Phase 1 + Phase 3 + Phase 4)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.table import Table

from agsuperbrain.terminal import TEXT_ENCODING, console

if TYPE_CHECKING:
    # Imported only for type-checking — actual use is via lazy runtime imports.
    from agsuperbrain.memory.graph.graph_store import GraphStore

app = typer.Typer(name="agsuperbrain", add_completion=False)
_DB = Path("./.agsuperbrain/graph")
_QDRANT = Path("./.agsuperbrain/qdrant")
_AUDIO = Path("./.agsuperbrain/audio")
_OUT = Path("./output/graph.html")
_PID_FILE = Path("./.agsuperbrain/watcher.pid")


# ── Dependency detection and repair ──────────────────────────────────────────

# (importable module name, PyPI distribution name, required). Required deps
# block the main ingest/query pipelines. Optional deps disable a feature
# (audio, LLM answers) but don't break core operation.
_RUNTIME_DEPS: tuple[tuple[str, str, bool], ...] = (
    ("kuzu", "kuzu", True),
    ("qdrant_client", "qdrant-client", True),
    ("tree_sitter", "tree-sitter", True),
    ("tree_sitter_language_pack", "tree-sitter-language-pack", True),
    ("sentence_transformers", "sentence-transformers", True),
    ("markitdown", "markitdown", True),
    ("llama_cpp", "llama-cpp-python", False),
    ("faster_whisper", "faster-whisper", False),
)


def _find_missing_deps(*, include_optional: bool = False) -> list[str]:
    """Return PyPI names for declared deps that can't be imported.

    Uses importlib.util.find_spec to avoid triggering module top-level side
    effects. Skips optional deps unless explicitly requested.
    """
    import importlib.util

    missing: list[str] = []
    for mod, pkg, required in _RUNTIME_DEPS:
        if not required and not include_optional:
            continue
        try:
            spec = importlib.util.find_spec(mod)
        except (ValueError, ModuleNotFoundError):
            spec = None
        if spec is None:
            missing.append(pkg)
    return missing


def _run_pip_install(packages: list[str]) -> bool:
    """Install packages via `sys.executable -m pip install -U`.

    Using sys.executable guarantees we target the same interpreter the CLI
    is running under — avoiding the classic "installed into a different
    Python" confusion.
    """
    import subprocess
    import sys

    if not packages:
        return True

    console.print(f"[dim]Running:[/dim] [cyan]{sys.executable} -m pip install -U {' '.join(packages)}[/cyan]\n")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", *packages],
        check=False,
    )
    return result.returncode == 0


def _mcp_server_config() -> dict:
    """Build MCP server config using absolute sys.executable.

    Returns base config without "type" field.
    Claude Code doesn't need it; Cursor adds it separately.
    """
    return {
        "command": sys.executable,
        "args": ["-u", "-m", "agsuperbrain", "mcp"],
    }


def _mcp_server_config_for_cursor() -> dict:
    """Build MCP server config for Cursor with type: stdio."""
    return {
        "type": "stdio",
        **_mcp_server_config(),
    }


def _check_mcp_installed() -> tuple[bool, str]:
    """Check if agsuperbrain is importable. Returns (success, error_message)."""
    import subprocess

    try:
        result = subprocess.run(
            [sys.executable, "-c", "import agsuperbrain"],
            capture_output=True,
            text=True,
            encoding=TEXT_ENCODING,
            errors="replace",
            timeout=10,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr or "unknown error"
    except Exception as e:
        return False, str(e)


def _mcp_config_portability_note() -> None:
    """Print a user-visible note about MCP-config portability limits."""
    console.print(
        f"[dim]MCP config uses absolute Python path: {sys.executable}[/dim]\n"
        "[dim]Re-run install command on other machines or environments.[/dim]"
    )


def _gitignore_add(path: Path, entries: list[str]) -> None:
    """Append entries to .gitignore if they aren't already present.

    Idempotent and non-destructive — leaves existing entries alone. Used to
    keep machine-specific files (MCP configs) out of version control so a
    config generated on one developer's machine doesn't accidentally get
    pushed and break a teammate's checkout on a different OS.
    """
    gitignore = path / ".gitignore"
    existing = gitignore.read_text(encoding=TEXT_ENCODING) if gitignore.exists() else ""
    missing = [e for e in entries if e not in existing]
    if not missing:
        return
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    addition = (
        prefix + "\n# Super-Brain (machine-specific; re-run install on each machine)\n" + "\n".join(missing) + "\n"
    )
    gitignore.write_text(existing + addition, encoding=TEXT_ENCODING)
    console.print(f"[dim]Added to .gitignore:[/dim] {', '.join(missing)}")


def _stop_watcher(path: Path = Path(".")) -> bool:
    """Stop the background watcher process, if any.

    Returns True if a watcher was running and was signalled; False if no
    watcher was running (or the PID file was stale/unreadable). In all cases
    the PID file is removed so a subsequent `init` starts a fresh watcher.
    """
    import signal

    pid_file = path / ".agsuperbrain" / "watcher.pid"
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text(encoding=TEXT_ENCODING).strip())
    except (OSError, ValueError):
        try:
            pid_file.unlink()
        except OSError:
            pass
        return False

    was_alive = _is_pid_alive(pid)
    if was_alive:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            # Process already gone between check and signal — benign race.
            pass

    try:
        pid_file.unlink()
    except OSError:
        pass

    return was_alive


def _is_pid_alive(pid: int) -> bool:
    """Return True iff a process with this PID is currently running.

    Cross-platform: POSIX uses signal 0; Windows uses the Win32 API directly
    because Windows does not implement signal-0-as-probe and raises OSError.
    """
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    # POSIX
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we cannot signal it — still alive.
        return True
    except OSError:
        # Anything unexpected — treat as not alive so the caller can recover.
        return False
    return True


def _resolve_package_version() -> str:
    """Best-effort resolve the installed agsuperbrain version.

    Prefers importlib.metadata (works in any pip-installed env) and falls
    back to reading pyproject.toml for source-checkout development.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("agsuperbrain")
    except PackageNotFoundError:
        pass

    # Source-checkout fallback. Walk up from this file looking for pyproject.toml.
    try:
        import tomllib

        here = Path(__file__).resolve()
        for parent in (here.parent, *here.parents):
            pyproject = parent / "pyproject.toml"
            if pyproject.is_file():
                with pyproject.open("rb") as f:
                    data = tomllib.load(f)
                return data.get("project", {}).get("version", "unknown")
    except Exception:
        pass

    return "unknown"


def _version_callback(value: bool) -> None:
    """Eager `--version` handler.

    Exits as soon as the flag is parsed so other arguments can't trigger
    side effects (no init, no doctor, no anything). Prints the package
    version, the Python interpreter that loaded it, and the on-disk
    location of the package — three things you need when diagnosing
    "wrong agsuperbrain installed".
    """
    if not value:
        return
    import sys

    import agsuperbrain as _self_pkg

    pkg_version = _resolve_package_version()
    pkg_path = Path(_self_pkg.__file__).resolve().parent if getattr(_self_pkg, "__file__", None) else None

    console.print(f"agsuperbrain {pkg_version}")
    console.print(f"[dim]python:  {sys.executable}[/dim]")
    if pkg_path:
        console.print(f"[dim]source:  {pkg_path}[/dim]")
    raise typer.Exit()


@app.callback()
def _global_callback(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", is_flag=True),
    # `version` is consumed by `_version_callback` via Typer's eager-callback
    # plumbing, not in this function body — pyrefly may flag it as unused.
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print agsuperbrain version (and Python + install path) and exit.",
    ),
) -> None:
    """Global callback — intentionally minimal.

    Earlier versions auto-restarted a dead watcher here. That proved to be
    the wrong place: commands such as `doctor`, `stop`, and `clean` must
    be side-effect free, and silent watcher restarts on every invocation
    surprised users. The watcher is now started only by explicit commands:
    `init` (once) or `watch` (foreground).

    This callback still exists so Typer treats `agsuperbrain` as a command
    group with shared `--verbose` and `--version` flags.
    """
    return


def _start_watcher_background(path: Path = Path(".")) -> None:
    """Start watcher in background daemon mode."""
    import subprocess

    config_dir = path / ".agsuperbrain"
    config_dir.mkdir(parents=True, exist_ok=True)

    pid_file = config_dir / "watcher.pid"

    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text(encoding=TEXT_ENCODING).strip())
        except (OSError, ValueError):
            old_pid = -1

        if old_pid > 0 and _is_pid_alive(old_pid):
            console.print(f"[dim]Watcher already running (PID {old_pid})[/dim]")
            return

        try:
            pid_file.unlink()
        except OSError:
            pass

    env = os.environ.copy()
    env["AGSB_DAEMON"] = "1"

    # start_new_session is POSIX-only; on Windows, use DETACHED_PROCESS instead.
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
    }
    if os.name == "nt":
        # 0x00000008 = DETACHED_PROCESS — the child has no console attached.
        popen_kwargs["creationflags"] = 0x00000008
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        ["agsuperbrain", "watch", str(path)],
        cwd=str(path.resolve()),
        **popen_kwargs,
    )

    pid_file.write_text(str(proc.pid), encoding=TEXT_ENCODING)
    console.print(f"[green]✓[/green] Watcher started (PID {proc.pid})")


def _store(db: Path):
    from agsuperbrain.memory.graph.graph_store import GraphStore

    s = GraphStore(db)
    s.init_schema()
    return s


def _generate_reports(gs: GraphStore, project_path: Path = Path(".")) -> None:
    """Generate graph.html and GRAPH_REPORT.md in .agsuperbrain directory."""
    from agsuperbrain.analytics.report import generate_report
    from agsuperbrain.memory.graph.visualizer import visualize as viz

    output_dir = (project_path / ".agsuperbrain").resolve()
    html_path = output_dir / "graph.html"
    report_path = output_dir / "GRAPH_REPORT.md"

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        viz(gs, html_path, None, 3)
        console.print(f"[dim]Updated:[/dim] {html_path}")
    except Exception as e:
        console.print(f"[yellow]Warning: failed to generate graph.html: {e}[/yellow]")

    try:
        md = generate_report(gs)
        report_path.write_text(md, encoding=TEXT_ENCODING)
        console.print(f"[dim]Updated:[/dim] {report_path}")
    except Exception as e:
        console.print(f"[yellow]Warning: failed to generate GRAPH_REPORT.md: {e}[/yellow]")


_CONFIG_YAML_TEMPLATE = """# Super-Brain configuration
# See docs for all options

# Exclude directories (added to defaults)
exclude: []

# Languages to index (default: all supported)
languages:
  - python
  - javascript
  - typescript

# Watcher settings
watcher:
  debounce_ms: 400
  max_wait_ms: 2000

# Graph settings
graph:
  db_path: ./.agsuperbrain/graph

# Vector settings
vector:
  db_path: ./.agsuperbrain/qdrant
"""

_IGNORE_FILE_TEMPLATE = """# Super-Brain package-specific ignores
# These are internal to the package, not user code
*.log
"""


def _write_config_scaffold(path: Path) -> None:
    """Create .agsuperbrain/config.yaml, .agsuperbrainignore, and patch .gitignore.

    Idempotent: does nothing for files that already exist.
    """
    config_dir = path / ".agsuperbrain"
    config_dir.mkdir(exist_ok=True)

    config_file = config_dir / "config.yaml"
    if not config_file.exists():
        config_file.write_text(_CONFIG_YAML_TEMPLATE, encoding=TEXT_ENCODING)
        console.print(f"[green]Created:[/green] {config_file}")

    ignore_file = path / ".agsuperbrainignore"
    if not ignore_file.exists():
        ignore_file.write_text(_IGNORE_FILE_TEMPLATE, encoding=TEXT_ENCODING)
        console.print(f"[green]Created:[/green] {ignore_file}")

    gitignore = path / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding=TEXT_ENCODING)
        if ".agsuperbrain/" not in content or ".agsuperbrainignore" not in content:
            gitignore.write_text(content + "\n# Super-Brain\n.agsuperbrain/\n.agsuperbrainignore\n", encoding=TEXT_ENCODING)
            console.print("[green]Updated:[/green] .gitignore")


def _do_full_init(
    path: Path,
    src: Path | None = None,
    skip_ingest: bool = False,
    *,
    show_next_steps: bool = True,
) -> None:
    """Full first-time setup: scaffold + dep preflight + ingest + index + watcher.

    This is the shared body used by the `init` command and by the
    self-healing `_ensure_initialized` path. Keeping both in one function
    guarantees that running `agsuperbrain <ide>-install` on a fresh
    project yields the exact same end-state as running `agsuperbrain init`.
    """
    _write_config_scaffold(path)

    console.print(f"\n[bold green]✓[/bold green] Super-Brain initialized in {path}")

    ingest_target: Path | None = None
    if not skip_ingest:
        if src is not None:
            if src.exists():
                ingest_target = src
            else:
                console.print(f"\n[yellow]Source path {src} does not exist. Skipping initial ingest.[/yellow]")
        else:
            ingest_target = _detect_source_dir(path)
            if ingest_target is None:
                console.print(
                    "\n[dim]No source directory detected. "
                    "Run `agsuperbrain ingest <path>` when you have code to "
                    "index.[/dim]"
                )

    # Track whether the ingest ran cleanly. If not, skip starting the
    # watcher — a watcher that hits the same missing import just hides the
    # failure behind a "running" PID and confuses the user.
    deps_ok = True

    # Preflight: if required deps are missing, offer to install them now.
    if ingest_target is not None:
        missing = _find_missing_deps()
        if missing:
            console.print(f"\n[yellow]Missing runtime dependencies ({len(missing)}):[/yellow] {', '.join(missing)}")
            if typer.confirm("Install them now?", default=True):
                if _run_pip_install(missing):
                    still_missing = _find_missing_deps()
                    if still_missing:
                        deps_ok = False
                        console.print(
                            f"\n[red]pip reported success but these are still missing:[/red] "
                            f"{', '.join(still_missing)}\n"
                            f"  Likely cause: no wheels for your Python/platform. "
                            f"See [cyan]agsuperbrain doctor[/cyan]."
                        )
                    else:
                        console.print("[green]✓[/green] Dependencies installed.\n")
                else:
                    deps_ok = False
                    console.print(
                        "\n[red]pip install failed.[/red] "
                        "See the output above, then retry with [cyan]agsuperbrain repair[/cyan]."
                    )
            else:
                deps_ok = False
                console.print(
                    "[dim]OK, skipping install. Run [cyan]agsuperbrain repair[/cyan] when you're ready.[/dim]"
                )

    if ingest_target is not None and deps_ok:
        console.print(
            f"\n[bold cyan]Ingesting[/bold cyan] [green]{ingest_target}[/green] "
            f"[dim](use --skip-ingest to opt out)[/dim]"
        )
        try:
            from agsuperbrain.core.pipeline import CodeGraphPipeline

            CodeGraphPipeline(_store(_DB)).run([ingest_target], verbose=False)
        except ImportError as exc:
            deps_ok = False
            console.print(
                f"\n[yellow]Ingest skipped — missing runtime dependency:[/yellow] "
                f"[dim]{exc}[/dim]\n"
                f"  Fix:  [cyan]agsuperbrain repair[/cyan]  "
                f"[dim](installs missing deps into this env)[/dim]\n"
                f"  Then retry:  [cyan]agsuperbrain ingest .[/cyan]"
            )
        except Exception as exc:
            console.print(
                f"\n[yellow]Ingest skipped due to error:[/yellow] {exc}\n"
                f"  Retry after fixing:  [cyan]agsuperbrain ingest .[/cyan]"
            )
        else:
            console.print("\n[bold cyan]Building vector index...[/bold cyan]")
            try:
                from agsuperbrain.core.index_pipeline import VectorIndexPipeline
                from agsuperbrain.memory.graph.graph_store import GraphStore
                from agsuperbrain.memory.vector.embedder import TextEmbedder
                from agsuperbrain.memory.vector.vector_store import VectorStore

                gs = GraphStore(_DB)
                gs.init_schema()
                vs = VectorStore(db_path=_QDRANT)
                total = VectorIndexPipeline(gs, vs, TextEmbedder()).run(incremental=True)
                console.print(f"[bold green]✓[/bold green] {total} vectors indexed.")

                console.print("\n[bold cyan]Generating reports...[/bold cyan]")
                _generate_reports(gs, path)
            except ImportError as exc:
                deps_ok = False
                console.print(
                    f"\n[yellow]Vector indexing skipped — missing runtime dependency:[/yellow] "
                    f"[dim]{exc}[/dim]\n"
                    f"  Fix:  [cyan]agsuperbrain repair[/cyan]\n"
                    f"  Then retry:  [cyan]agsuperbrain index-vectors[/cyan]"
                )
            except Exception as exc:
                console.print(
                    f"\n[yellow]Vector indexing skipped due to error:[/yellow] {exc}\n"
                    f"  Retry after fixing:  [cyan]agsuperbrain index-vectors[/cyan]"
                )

    if deps_ok and ingest_target is not None:
        console.print("\n[bold cyan]Starting background watcher...[/bold cyan]")
        _start_watcher_background(path)
        console.print("[dim]Watcher is now running in background.[/dim]")
        console.print("Your code will be automatically indexed as you work!")

    if show_next_steps:
        console.print(
            "\n[bold]Next:[/bold] wire Super-Brain into your AI coding tool:\n"
            "  [cyan]agsuperbrain claude-install[/cyan]   "
            "[dim]# or cursor-install / aider-install / codex-install / ...[/dim]\n"
            "  [cyan]agsuperbrain install --platform all[/cyan]  "
            "[dim]# all 14 supported tools at once[/dim]"
        )


def _ensure_initialized(path: Path = Path(".")) -> bool:
    """Run the full init flow if the project isn't set up yet.

    Used by `<ide>-install` commands so a user running (e.g.)
    `agsuperbrain cursor-install` on a fresh project gets a complete
    setup — config + ingest + vector index + watcher — before the IDE
    is wired up. Otherwise the IDE would point at an empty graph.

    Returns True if the project was freshly initialized, False if
    it was already set up (no-op).
    """
    config_dir = path / ".agsuperbrain"
    ignore_file = path / ".agsuperbrainignore"

    if config_dir.exists() and ignore_file.exists():
        return False

    console.print("[dim]Super-Brain not initialized. Running full first-time setup...[/dim]")
    _do_full_init(path, src=None, skip_ingest=False, show_next_steps=False)
    return True


# ── Phase 1: Code ─────────────────────────────────────────────────────────────


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(...),
    db: Path = typer.Option(_DB, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v", is_flag=True),
) -> None:
    """Ingest source code into the graph."""
    from agsuperbrain.core.pipeline import CodeGraphPipeline

    CodeGraphPipeline(_store(db)).run(paths, verbose)


# ── Phase 3: Documents ────────────────────────────────────────────────────────


@app.command(name="ingest-doc")
def ingest_doc(
    paths: list[Path] = typer.Argument(...),
    db: Path = typer.Option(_DB, "--db"),
    verbose: bool = typer.Option(False, "--verbose", "-v", is_flag=True),
) -> None:
    """Ingest documents (PDF, DOCX, PPTX, Markdown…) into the graph."""
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from agsuperbrain.extraction.doc_extractor import DocExtractor
    from agsuperbrain.preprocessing.doc_parser import DocParser, is_document

    store = _store(db)
    parser = DocParser()
    extractor = DocExtractor()

    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            for f in p.rglob("*"):
                if is_document(f):
                    files.append(f)
        elif p.is_file() and is_document(p):
            files.append(p)

    if not files:
        console.print("[yellow]No supported document files found.[/yellow]")
        raise typer.Exit()

    console.rule("[bold cyan]Super-Brain · Phase 3: Document Ingestion")
    console.print(f"[dim]{len(files)} document(s) to process.[/dim]\n")

    ok = failed = total_sections = total_concepts = 0
    with Progress(
        SpinnerColumn("line"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("Processing…", total=len(files))
        for fp in files:
            prog.update(task, description=f"[cyan]{fp.name}[/cyan]")
            try:
                pr = parser.parse(fp)
                ex = extractor.extract(pr)
                store.upsert_doc(ex)
                ok += 1
                total_sections += len(ex.sections)
                total_concepts += len(ex.concepts)
                if verbose:
                    console.print(
                        f"  ✓ [green]{fp.name}[/green] "
                        f"[dim]— {len(ex.sections)} sections, "
                        f"{len(ex.concepts)} concepts[/dim]"
                    )
            except Exception as e:
                failed += 1
                console.print(f"  ✗ [red]{fp.name}[/red] — {e}")
            prog.advance(task)

    console.rule("[bold green]Done")
    console.print(f"  Documents : {ok}")
    console.print(f"  Sections  : {total_sections}")
    console.print(f"  Concepts  : {total_concepts}")
    if failed:
        console.print(f"  [red]Errors    : {failed}[/red]")


# ── Phase 4: Audio / Video ────────────────────────────────────────────────────


@app.command(name="ingest-audio")
def ingest_audio(
    sources: list[str] = typer.Argument(
        ...,
        help="YouTube URLs or local audio/video file paths",
    ),
    db: Path = typer.Option(_DB, "--db"),
    model_size: str = typer.Option("base", "--model", "-m", help="Whisper model: tiny/base/small/medium"),
    cache_dir: Path = typer.Option(_AUDIO, "--cache"),
    verbose: bool = typer.Option(False, "--verbose", "-v", is_flag=True),
) -> None:
    """
    Transcribe audio/video (URL or local file) into the graph.

    Examples:
        superbrain ingest-audio https://youtu.be/xxxx
        superbrain ingest-audio ./talk.mp4 --model small
        superbrain ingest-audio https://youtu.be/xxxx ./lecture.mp3
    """
    from agsuperbrain.extraction.audio_extractor import AudioExtractor
    from agsuperbrain.preprocessing.audio_fetcher import AudioFetcher

    store = _store(db)
    fetcher = AudioFetcher(cache_dir=cache_dir)
    extractor = AudioExtractor(model_size=model_size)

    console.rule("[bold cyan]Super-Brain · Phase 4: Audio/Video Ingestion")
    console.print(f"[dim]{len(sources)} source(s) | model: {model_size}[/dim]\n")

    for src in sources:
        console.print(f"[cyan]▶ {src}[/cyan]")
        try:
            # Step 1: fetch / download → .wav
            console.print("  [dim]Fetching audio…[/dim]")
            af = fetcher.fetch(src)
            console.print(f"  [dim]→ {af.wav_path.name}  title: {af.title!r}[/dim]")

            # Step 2: transcribe → segments
            console.print("  [dim]Transcribing (this may take a while on CPU)…[/dim]")
            ex = extractor.extract(af)
            console.print(f"  [dim]→ {len(ex.segments)} segments  duration: {ex.source.duration_s:.1f}s[/dim]")

            # Step 3: write to graph
            store.upsert_audio(ex)
            console.print("  [green]✓ Ingested[/green]")

            if verbose:
                for seg in ex.segments[:5]:
                    console.print(f"    [{seg.start_sec:.1f}s → {seg.end_sec:.1f}s] [dim]{seg.text[:80]}[/dim]")
                if len(ex.segments) > 5:
                    console.print(f"    [dim]... {len(ex.segments) - 5} more segments[/dim]")

        except Exception as e:
            console.print(f"  [red]✗ Failed[/red] — {e}")

    console.rule("[bold green]Done")


# ── Shared commands ───────────────────────────────────────────────────────────


@app.command()
def visualize(
    db: Path = typer.Option(_DB, "--db"),
    output: Path = typer.Option(_OUT, "--output", "-o"),
    root: str | None = typer.Option(None, "--root", "-r"),
    depth: int = typer.Option(3, "--depth", "-d"),
) -> None:
    """Generate interactive HTML graph."""
    from agsuperbrain.memory.graph.visualizer import visualize as viz

    viz(_store(db), output, root, depth)
    console.print(f"\n[dim]Open:[/dim] file://{output.resolve()}")


@app.command()
def query(
    cypher: str = typer.Argument(...),
    db: Path = typer.Option(_DB, "--db"),
) -> None:
    """Run a raw Cypher query."""
    rows = _store(db).query(cypher)
    if not rows:
        console.print("[dim]No results.[/dim]")
        return
    t = Table(header_style="bold cyan")
    for i in range(len(rows[0])):
        t.add_column(f"col_{i}")
    for r in rows:
        t.add_row(*[str(v) for v in r])
    console.print(t)


@app.command()
def stats(db: Path = typer.Option(_DB, "--db")) -> None:
    """Show graph statistics across all phases."""
    s = _store(db)
    t = Table(title="Graph Stats", header_style="bold cyan")
    t.add_column("Metric")
    t.add_column("Count", justify="right")
    t.add_column("Phase", justify="center")
    for label, q, phase in [
        ("Modules", "MATCH (m:Module)      RETURN count(m)", "1"),
        ("Functions", "MATCH (f:Function)    RETURN count(f)", "1"),
        ("Call edges", "MATCH ()-[:CALLS]->() RETURN count(*)", "1"),
        ("Documents", "MATCH (d:Document)    RETURN count(d)", "3"),
        ("Sections", "MATCH (s:Section)     RETURN count(s)", "3"),
        ("Concepts", "MATCH (c:Concept)     RETURN count(c)", "3"),
        ("Audio sources", "MATCH (a:AudioSource) RETURN count(a)", "4"),
        ("Transcript segs", "MATCH (t:Transcript)  RETURN count(t)", "4"),
        ("FOLLOWS edges", "MATCH ()-[:FOLLOWS]->() RETURN count(*)", "4"),
    ]:
        rows = s.query(q)
        t.add_row(label, str(rows[0][0] if rows else 0), phase)
    console.print(t)


@app.command(name="index-vectors")
def index_vectors(
    db: Path = typer.Option(_DB, "--db"),
    qdrant_path: Path = typer.Option(_QDRANT, "--qdrant-path"),
    batch_size: int = typer.Option(64, "--batch-size"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Only embed nodes not already in Qdrant"),
) -> None:
    """Embed every graph node and store in local Qdrant."""
    from agsuperbrain.core.index_pipeline import VectorIndexPipeline
    from agsuperbrain.memory.graph.graph_store import GraphStore
    from agsuperbrain.memory.vector.embedder import TextEmbedder
    from agsuperbrain.memory.vector.vector_store import VectorStore

    gs = GraphStore(db)
    gs.init_schema()
    vs = VectorStore(db_path=qdrant_path)
    emb = TextEmbedder()

    total = VectorIndexPipeline(gs, vs, emb, batch_size=batch_size).run(incremental=incremental)
    console.print(f"[bold green]✓[/bold green] {total} vectors indexed.")


@app.command(name="search-vectors")
def search_vectors(
    query: str = typer.Argument(..., help="Natural language query"),
    limit: int = typer.Option(5, "--limit", "-k"),
    node_type: str = typer.Option("", "--type", "-t", help="Filter: Function|Section|Concept|Transcript"),
    source_type: str = typer.Option("", "--source-type", "-s", help="Filter: code|document|audio|external"),
    qdrant_path: Path = typer.Option(_QDRANT, "--qdrant-path"),
) -> None:
    """Semantic search over all indexed graph nodes."""
    from agsuperbrain.memory.vector.embedder import TextEmbedder
    from agsuperbrain.memory.vector.vector_store import VectorStore

    emb = TextEmbedder()
    vs = VectorStore(db_path=qdrant_path)
    qvec = emb.embed([query])[0]

    results = vs.search(
        qvec,
        limit=limit,
        node_type=node_type or None,
        source_type=source_type or None,
    )

    if not results:
        console.print("[yellow]No results.[/yellow]")
        return

    t = Table(title=f'Search: "{query}"', header_style="bold cyan")
    t.add_column("Score", justify="right", style="bold green")
    t.add_column("Type", style="cyan")
    t.add_column("Text", max_width=60)
    t.add_column("Source", style="dim")

    for r in results:
        src_short = r.source_path.split("/")[-1] if r.source_path else ""
        t.add_row(
            f"{r.score:.4f}",
            r.node_type,
            r.text[:100],
            src_short,
        )
    console.print(t)


@app.command()
def report(
    db: Path = typer.Option(_DB, "--db"),
    out: Path = typer.Option(Path("./GRAPH_REPORT.md"), "--out", "-o"),
) -> None:
    """Generate GRAPH_REPORT.md summarising the graph (god-nodes, cross-module deps, orphans, suggested questions)."""
    from agsuperbrain.analytics.report import generate_report

    md = generate_report(_store(db))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding=TEXT_ENCODING)
    console.print(f"[bold green]✓[/bold green] Wrote {out}")


@app.command(name="inspect-function")
def inspect_function(
    name: str = typer.Argument(..., help="Qualified name (e.g. 'DataProcessor.process') or bare name ('process')"),
    db: Path = typer.Option(_DB, "--db"),
) -> None:
    """Dump body + docstring for a function straight from KùzuDB (diagnostic)."""
    s = _store(db)
    rows = s.query(
        "MATCH (f:Function) "
        "WHERE f.qualified_name = $q OR f.name = $q "
        "RETURN f.qualified_name, f.source_path, f.start_line, f.end_line, "
        "       f.is_method, f.class_name, f.docstring, f.body",
        {"q": name},
    )
    if not rows:
        console.print(f"[yellow]No function matches[/yellow] {name!r}")
        raise typer.Exit(code=1)

    for r in rows:
        qn, src, sl, el, is_m, cn, doc, body = r
        console.rule(f"[bold cyan]{qn}[/bold cyan]")
        console.print(f"[dim]source:[/dim] {src}:{sl}-{el}")
        if is_m:
            console.print(f"[dim]class:[/dim]  {cn or ''}")
        console.print(f"[dim]docstring ({len(doc or '')} chars):[/dim]")
        console.print((doc or "").strip() or "[dim](empty)[/dim]")
        console.print(f"\n[dim]body ({len(body or '')} chars):[/dim]")
        console.print(body or "[dim](empty)[/dim]")


@app.command(name="watch")
def watch(
    paths: list[Path] | None = typer.Argument(
        None,
        help="Paths to watch. Default: current directory (.).",
    ),
    db: Path = typer.Option(_DB, "--db"),
    qdrant: Path = typer.Option(_QDRANT, "--qdrant"),
    use_poll: bool = typer.Option(
        False,
        "--use-poll",
        help="Legacy: rglob+MD5+sleep. Use on NFS/SMB; default is OS file events + debounce.",
    ),
    poll_secs: float = typer.Option(2.0, "--poll", "-p", help="With --use-poll: seconds between scans"),
    debounce: float | None = typer.Option(
        None,
        "--debounce",
        "-d",
        help="Debounce for event mode (seconds). "
        "Default: .agsuperbrain/config.yaml watcher.debounce_ms, or 400 ms if unset.",
    ),
    max_wait: float | None = typer.Option(
        None,
        "--max-wait",
        help="Max time to wait before forcing a flush during continuous edits (seconds). "
        "Default: config watcher.max_wait_ms, or 2.0s if unset.",
    ),
    once: bool = typer.Option(False, "--once", "-1", help="Single pass instead of continuous"),
) -> None:
    """
    Watch directories for file changes and incrementally re-index.

    Default: kernel file events + debounce (low idle CPU). Use --use-poll on network shares.

    Examples:
        agsuperbrain watch ./src
        agsuperbrain watch ./src --once
        agsuperbrain watch ./src --use-poll --poll 5
    """
    from agsuperbrain.core.config import SUPERBRAIN_DIR, get_config
    from agsuperbrain.core.pipeline import DEFAULT_EXCLUDE_DIRS
    from agsuperbrain.core.watcher import FileWatcher
    from agsuperbrain.memory.graph.graph_store import GraphStore
    from agsuperbrain.memory.vector.vector_store import VectorStore

    watch_paths = paths or [Path(".")]

    def _config_root(anchor: Path) -> Path:
        base = anchor.resolve()
        start = base if base.is_dir() else base.parent
        cur: Path = start
        for _ in range(64):
            if (cur / SUPERBRAIN_DIR / "config.yaml").is_file():
                return cur
            if cur.parent == cur:
                return Path.cwd()
            cur = cur.parent
        return Path.cwd()

    project_root = _config_root(watch_paths[0])
    first = watch_paths[0].resolve()
    if project_root.resolve() != first:
        console.print(
            f"[dim]Watching {first}[/dim]\n"
            f"[dim]Project root detected as {project_root.resolve()} — outputs stay in "
            f"{(project_root / SUPERBRAIN_DIR).resolve()}[/dim]"
        )

    cfg = get_config(project_root)
    debounce_s = float(debounce) if debounce is not None else cfg.watcher_debounce_ms / 1000.0
    max_wait_s = float(max_wait) if max_wait is not None else cfg.watcher_max_wait_ms / 1000.0

    gs = GraphStore(db)
    gs.init_schema()
    vs = VectorStore(db_path=qdrant)

    watcher = FileWatcher(
        gs,
        vs,
        watch_paths,
        exclude_dirs=DEFAULT_EXCLUDE_DIRS,
    )
    if once:
        watcher.run_once()
    else:
        watcher.start(
            debounce=debounce_s,
            max_wait=max_wait_s,
            use_polling=use_poll,
            poll_interval=poll_secs,
        )


@app.command(name="link")
def link_crossmodal(
    db: Path = typer.Option(_DB, "--db"),
    mode: str = typer.Option("all", "--mode", "-m", help="Linking mode: all|documented|mentions"),
) -> None:
    """
    Create cross-modal links between graph layers.

    Links:
      - documented_by: Section → Function (via keyword matching)
      - mentions: Transcript → Function/Concept (via keyword matching)

    Examples:
        superbrain link
        superbrain link --mode documented
        superbrain link --mode mentions
    """
    from agsuperbrain.core.pipeline import link_documented_by, link_mentions

    gs = _store(db)
    gs.init_schema()

    console.rule("[bold cyan]Super-Brain · Cross-Modal Linking")

    linked = 0
    if mode in ("all", "documented"):
        console.print("[dim]Linking documents to functions…[/dim]")
        linked += link_documented_by(gs)
        console.print(f"  [dim]{linked} DOCUMENTED_BY links created[/dim]")

    if mode in ("all", "mentions"):
        mentions = link_mentions(gs)
        console.print(f"  [dim]{mentions} MENTIONS links created[/dim]")
        linked += mentions

    console.print(f"[bold green]✓[/bold green] {linked} cross-modal links created")


@app.command(name="stop")
def stop_cmd(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory"),
) -> None:
    """
    Stop the background watcher. Data is preserved.

    Use this when you want to pause indexing without deleting the graph.
    Re-run `agsuperbrain init` (or any ingest command) to resume.

    Examples:
        agsuperbrain stop
        agsuperbrain stop --path ./my-project
    """
    if _stop_watcher(path):
        console.print("[green]✓[/green] Watcher stopped.")
    else:
        console.print("[dim]No watcher was running.[/dim]")


@app.command(name="watch-status")
def watch_status_cmd(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory"),
    stale_after_s: float = typer.Option(
        30.0,
        "--stale-after",
        help="Treat the watcher as DEAD if its heartbeat is older than this many seconds.",
    ),
) -> None:
    """Show background watcher status (current batch, last flush, last error).

    Heartbeat freshness — not the JSON field `worker_alive` — is the source of
    truth for liveness. The `worker_alive` field is captured at status-write
    time and goes stale instantly if the watcher hangs; the heartbeat age is
    computed against the wall clock right now and catches hung processes
    where the JSON would otherwise lie.
    """
    import json
    from datetime import UTC, datetime

    root = path.resolve()
    status_path = root / ".agsuperbrain" / "watcher.status.json"
    pid_path = root / ".agsuperbrain" / "watcher.pid"

    running = False
    pid = None
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding=TEXT_ENCODING).strip())
            running = _is_pid_alive(pid)
        except Exception:
            pid = None
            running = False

    console.rule("[bold cyan]Super-Brain · Watcher status")
    if pid is not None:
        console.print(f"[dim]PID:[/dim] {pid} ({'running' if running else 'not running'})")
    else:
        console.print("[dim]PID:[/dim] (unknown)")

    if not status_path.exists():
        console.print(f"[yellow]No status file found:[/yellow] {status_path}")
        console.print("[dim]Start the watcher once to create it: `agsuperbrain watch .`[/dim]")
        return

    try:
        data = json.loads(status_path.read_text(encoding=TEXT_ENCODING))
    except Exception as exc:
        console.print(f"[yellow]Could not read status file:[/yellow] {exc}")
        return

    state = data.get("state")
    state_color = {
        "idle": "green",
        "pending": "yellow",
        "flushing": "cyan",
        "error": "red",
    }.get(str(state), "dim")
    backend = data.get("backend") or "legacy"
    console.print(f"[dim]Backend:[/dim] {backend}")
    console.print(f"[dim]State:[/dim] [{state_color}]{state}[/{state_color}]")
    console.print(f"[dim]Updated:[/dim] {data.get('updated_at')}")
    console.print(f"[dim]Last heartbeat:[/dim] {data.get('last_heartbeat_at') or '(never)'}")
    console.print(f"[dim]Last flush:[/dim] {data.get('last_flush_at') or '(never)'}")
    if data.get("batches_processed") is not None:
        console.print(
            f"[dim]Lifetime totals:[/dim] {data.get('batches_processed')} batches, "
            f"{data.get('files_processed')} files indexed"
        )

    # ── Liveness: heartbeat-age check, NOT the stale `worker_alive` field ──
    heartbeat_age_s: float | None = None
    last_hb = data.get("last_heartbeat_at")
    if last_hb:
        try:
            hb_dt = datetime.fromisoformat(str(last_hb))
            now = datetime.now(UTC) if hb_dt.tzinfo else datetime.now()
            heartbeat_age_s = (now - hb_dt).total_seconds()
        except Exception:
            heartbeat_age_s = None

    if heartbeat_age_s is None:
        liveness = "unknown"
    elif heartbeat_age_s < stale_after_s:
        liveness = "alive"
    else:
        liveness = "dead"

    if liveness == "alive":
        console.print(f"[dim]Liveness:[/dim] [green]alive[/green] (heartbeat {heartbeat_age_s:.1f}s old)")
    elif liveness == "dead":
        console.print(
            f"[dim]Liveness:[/dim] [red]DEAD[/red] — heartbeat is "
            f"[bold]{heartbeat_age_s:.0f}s[/bold] old (threshold: {stale_after_s:.0f}s).\n"
            f"  The PID may still be running but the watcher loop is hung. Restart:\n"
            f"  [cyan]agsuperbrain stop && agsuperbrain init[/cyan]"
        )
    else:
        console.print("[dim]Liveness:[/dim] unknown (no heartbeat data)")

    # ── Stuck-pending diagnostic ─────────────────────────────────────────
    # Now branches on heartbeat-age, not the stale `worker_alive` field.
    if state == "pending" and not data.get("last_flush_at"):
        if liveness == "dead":
            console.print(
                "[yellow]⚠ Stuck:[/yellow] state=pending but heartbeat is stale — "
                "the watcher process is hung mid-batch. Restart with "
                "[cyan]agsuperbrain stop && agsuperbrain init[/cyan]."
            )
        elif backend == "watchfiles":
            # New backend: trailing-edge debounce only. Either we just got an
            # event (normal) or events keep firing (AV / indexer noise).
            cur_size = data.get("current_batch_size") or data.get("pending_count")
            console.print(
                f"[cyan]In-flight:[/cyan] {cur_size} file(s) in current batch, "
                f"waiting for trailing-edge debounce.\n"
                "[dim]watchfiles will flush ~debounce ms after the LAST event for these paths.\n"
                "If state stays 'pending' for >5 seconds while heartbeat advances, "
                "events keep firing on the file (AV / indexer / IDE).[/dim]"
            )
        else:
            # Legacy backend — keep the old detailed diagnostic for users still
            # on a watcher process started before the watchfiles rewrite.
            sec_evt = data.get("seconds_since_last_event")
            sec_first = data.get("seconds_since_first_event")
            debounce_s_legacy = data.get("debounce_s") or 0.4
            max_wait_s_legacy = data.get("max_wait_s") or 2.0
            chk = data.get("checks_since_queue")
            evt = data.get("events_since_queue")
            console.print(
                "[yellow]⚠ Pending on legacy watcher:[/yellow]\n"
                f"  Inner-loop checks since queue:   [bold]{chk}[/bold]\n"
                f"  File events since queue:         [bold]{evt}[/bold]\n"
                f"  Seconds since last event:        [bold]{sec_evt}[/bold] "
                f"(debounce_s={debounce_s_legacy})\n"
                f"  Seconds since first event:       [bold]{sec_first}[/bold] "
                f"(max_wait_s={max_wait_s_legacy})\n"
                "[dim]Stop and restart so the new watchfiles backend takes effect:\n"
                "  [cyan]agsuperbrain stop && agsuperbrain init[/cyan][/dim]"
            )

    console.print(f"[dim]Pending:[/dim] {data.get('pending_count')}")
    if data.get("pending_paths"):
        for p in data["pending_paths"]:
            console.print(f"  [dim]- {p}[/dim]")
    if data.get("last_indexed_paths"):
        console.print(f"[dim]Last indexed ({len(data['last_indexed_paths'])}):[/dim]")
        for p in data["last_indexed_paths"][:5]:
            console.print(f"  [dim]- {p}[/dim]")
    if data.get("last_error"):
        console.print(f"\n[yellow]Last error:[/yellow]\n{data.get('last_error')}")


@app.command(name="repair")
def repair_cmd(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    include_optional: bool = typer.Option(
        False,
        "--include-optional",
        help="Also install optional deps (llama-cpp-python, faster-whisper)",
    ),
) -> None:
    """
    Install any missing runtime dependencies into the current Python env.

    Uses the same Python interpreter that's running this CLI (via
    `sys.executable -m pip install`), so the installed packages are always
    available to subsequent `agsuperbrain` commands — no env-mismatch risk.

    Examples:
        agsuperbrain repair                        # prompts before installing
        agsuperbrain repair --yes                  # no prompt (scripts / CI)
        agsuperbrain repair --include-optional     # also install LLM/audio deps
    """
    missing = _find_missing_deps(include_optional=include_optional)
    if not missing:
        console.print("[green]✓ All required dependencies are installed.[/green]")
        if not include_optional:
            optional_missing = [
                pkg for mod, pkg, req in _RUNTIME_DEPS if not req and pkg in _find_missing_deps(include_optional=True)
            ]
            if optional_missing:
                console.print(
                    f"[dim]Optional (not installed):[/dim] {', '.join(optional_missing)}\n"
                    f"[dim]Run[/dim] [cyan]agsuperbrain repair --include-optional[/cyan] "
                    f"[dim]to add them.[/dim]"
                )
        return

    console.print(f"[yellow]Missing {len(missing)} dependency(ies):[/yellow]")
    for pkg in missing:
        console.print(f"  • {pkg}")

    if not yes and not typer.confirm("\nInstall them now?", default=True):
        console.print("[dim]Cancelled. No changes made.[/dim]")
        raise typer.Exit()

    if _run_pip_install(missing):
        # Re-check to confirm the install actually took effect.
        still_missing = _find_missing_deps(include_optional=include_optional)
        if still_missing:
            console.print(
                f"\n[yellow]pip reported success but these are still missing:[/yellow] "
                f"{', '.join(still_missing)}\n"
                f"  Likely cause: wheels unavailable for your Python/platform "
                f"(see `agsuperbrain doctor`)."
            )
            raise typer.Exit(code=1)
        console.print("\n[bold green]✓[/bold green] Dependencies installed.")
    else:
        console.print(
            "\n[red]✗ pip install failed. See output above.[/red]\n"
            "Common fixes:\n"
            "  • Windows: install Visual Studio Build Tools 2022 (Desktop C++ workload)\n"
            "  • Python 3.14: not supported — downgrade to 3.11, 3.12, or 3.13\n"
            "  • See `agsuperbrain doctor` for component-level diagnosis"
        )
        raise typer.Exit(code=1)


@app.command(name="clean")
def clean(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """
    Stop the watcher and wipe all Super-Brain data for this project.

    Removes the entire .agsuperbrain/ directory (graph, vectors, audio cache,
    config, PID file), .agsuperbrainignore, and .gitignore entries.
    Your source code is never touched.

    Examples:
        agsuperbrain clean
        agsuperbrain clean --yes          # skip confirmation
        agsuperbrain clean --path ./repo
    """
    import re
    import shutil

    config_dir = path / ".agsuperbrain"
    ignore_file = path / ".agsuperbrainignore"
    gitignore = path / ".gitignore"

    if not config_dir.exists() and not ignore_file.exists():
        console.print("[dim]Nothing to clean — no .agsuperbrain/ or .agsuperbrainignore found.[/dim]")
        return

    if not yes:
        items = []
        if config_dir.exists():
            items.append(str(config_dir.resolve()))
        if ignore_file.exists():
            items.append(str(ignore_file.resolve()))
        console.print(f"[yellow]This will delete:[/yellow] {', '.join(items)}")
        if not typer.confirm("Proceed?"):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()

    # Stop watcher first so it can't re-create files mid-clean.
    if _stop_watcher(path):
        console.print("[dim]Stopped background watcher.[/dim]")

    try:
        if config_dir.exists():
            shutil.rmtree(config_dir)
            console.print(f"[red]Removed:[/red] {config_dir}")
    except OSError as exc:
        console.print(f"[yellow]Partial clean — {exc}[/yellow]")

    if ignore_file.exists():
        try:
            ignore_file.unlink()
            console.print(f"[red]Removed:[/red] {ignore_file}")
        except OSError as exc:
            console.print(f"[yellow]Partial clean — {exc}[/yellow]")

    if gitignore.exists():
        try:
            content = gitignore.read_text(encoding=TEXT_ENCODING)
            new_content = re.sub(r"\n# Super-Brain\n\.agsuperbrain/\n\.agsuperbrainignore\n", "", content)
            new_content = (
                re.sub(r"\n# Super-Brain\n\.agsuperbrain/\n", "", content) if new_content == content else new_content
            )
            new_content = re.sub(r"\n\.agsuperbrainignore\n", "", new_content)
            if new_content != content:
                gitignore.write_text(new_content, encoding=TEXT_ENCODING)
                console.print("[dim]Cleaned .gitignore entries.[/dim]")
        except Exception as exc:
            console.print(f"[yellow]Partial clean — {exc}[/yellow]")

    console.print("[bold green]✓[/bold green] Super-Brain data cleared.")


@app.command(name="doctor")
def doctor(
    db: Path = typer.Option(_DB, "--db"),
    qdrant: Path = typer.Option(_QDRANT, "--qdrant"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory"),
) -> None:
    """
    Run a read-only health check on the Super-Brain installation.

    Reports — without touching disk or starting processes:
      • Runtime dependencies (import-resolvable, not actually imported)
      • Optional system binaries (FFmpeg)
      • Data-directory state (graph + vector store contents)
      • Watcher state (running / not running / stale PID)

    Doctor never creates, modifies, or deletes anything.
    """
    import importlib.util
    import subprocess

    console.print("\n[bold cyan]Super-Brain Health Check[/bold cyan]\n")

    checks: list[tuple[str, str, str]] = []

    # ── Watcher state (read-only) ─────────────────────────────────────────
    pid_file = path / ".agsuperbrain" / "watcher.pid"
    watcher_pid: int | None = None
    watcher_running = False
    if pid_file.exists():
        try:
            watcher_pid = int(pid_file.read_text(encoding=TEXT_ENCODING).strip())
            watcher_running = _is_pid_alive(watcher_pid)
        except Exception:
            watcher_pid = None
            watcher_running = False

    # ── Runtime dependencies ──────────────────────────────────────────────
    # `find_spec` resolves the module without executing its top-level code,
    # so missing native libraries or heavy imports don't fire here.
    deps = [
        ("kuzu", "graph database"),
        ("qdrant_client", "vector store"),
        ("tree_sitter", "AST parser core"),
        ("tree_sitter_language_pack", "306-language grammars"),
        ("sentence_transformers", "embedder"),
        ("llama_cpp", "local LLM (optional)"),
        ("faster_whisper", "audio transcription (optional)"),
        ("markitdown", "document conversion (optional)"),
    ]
    for mod, role in deps:
        try:
            spec = importlib.util.find_spec(mod)
        except (ValueError, ModuleNotFoundError):
            spec = None
        label = f"{mod} [dim]({role})[/dim]"
        if spec is not None:
            checks.append((label, "OK", "green"))
        elif "optional" in role:
            checks.append((label, "missing (feature disabled)", "yellow"))
        else:
            checks.append((label, f"MISSING — pip install {mod.replace('_', '-')}", "red"))

    # ── FFmpeg (optional system binary) ──────────────────────────────────
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5, check=False)
        if result.returncode == 0:
            checks.append(("FFmpeg [dim](audio/video ingestion)[/dim]", "OK", "green"))
        else:
            checks.append(("FFmpeg [dim](audio/video ingestion)[/dim]", "not found (feature disabled)", "yellow"))
    except FileNotFoundError:
        checks.append(("FFmpeg [dim](audio/video ingestion)[/dim]", "not found (feature disabled)", "yellow"))
    except Exception as e:
        checks.append(("FFmpeg [dim](audio/video ingestion)[/dim]", f"error: {e}", "yellow"))

    # ── Data state (read-only) ────────────────────────────────────────────
    if db.exists():
        # Try counting functions without creating the DB. Wrapped in a
        # broad try so a missing `kuzu` dep doesn't error out this row.
        try:
            from agsuperbrain.memory.graph.graph_store import GraphStore

            gs = GraphStore(db)
            rows = gs.query("MATCH (f:Function) RETURN count(f)")
            gs.close()
            count = rows[0][0] if rows else 0
            if count > 0:
                checks.append(("Graph data", f"{count} functions indexed", "green"))
            else:
                checks.append(("Graph data", "initialized but empty (run `agsuperbrain ingest`)", "yellow"))
        except Exception as e:
            msg = str(e)
            if watcher_running and ("lock" in msg.lower() or "set lock" in msg.lower()):
                checks.append(
                    (
                        "Graph data",
                        f"in use by watcher (PID {watcher_pid}) — run `agsuperbrain stop` to inspect",
                        "yellow",
                    )
                )
            else:
                checks.append(("Graph data", f"present but unreadable: {e}", "red"))
    else:
        checks.append(("Graph data", "not initialized (run `agsuperbrain init`)", "yellow"))

    if qdrant.exists():
        try:
            from agsuperbrain.memory.vector.vector_store import VectorStore

            vs = VectorStore(db_path=qdrant)
            n = vs.count()
            if n > 0:
                checks.append(("Vector index", f"{n} vectors", "green"))
            else:
                checks.append(("Vector index", "empty (run `agsuperbrain index-vectors`)", "yellow"))
        except Exception as e:
            # No collection yet is the normal pre-ingest state, not a failure.
            msg = str(e)
            if "not found" in msg.lower() or "not_found" in msg.lower():
                checks.append(("Vector index", "no collection yet (run `agsuperbrain index-vectors`)", "yellow"))
            elif watcher_running and (
                "already accessed by another instance" in msg.lower() or "already accessed" in msg.lower()
            ):
                checks.append(
                    (
                        "Vector index",
                        f"in use by watcher (PID {watcher_pid}) — run `agsuperbrain stop` to inspect",
                        "yellow",
                    )
                )
            else:
                checks.append(("Vector index", f"error: {msg}", "red"))
    else:
        checks.append(("Vector index", "not initialized", "yellow"))

    # ── CLI on PATH ───────────────────────────────────────────────────────
    # Whether the `agsuperbrain` entry-point script is on PATH in the
    # current shell. Matters because IDE-spawned shells often don't
    # inherit the Python env's Scripts/ or bin/ directory, which breaks
    # plain-command MCP configs. MCP configs Super-Brain writes now use
    # `sys.executable -m agsuperbrain` to sidestep this, but users may
    # still be surprised by `agsuperbrain --help` failing in one terminal
    # while working in another.
    import shutil
    import sys

    cli_path = shutil.which("agsuperbrain")
    if cli_path:
        checks.append(("`agsuperbrain` on PATH", f"{cli_path}", "green"))
    else:
        checks.append(
            (
                "`agsuperbrain` on PATH",
                f"not found — use `{sys.executable} -m agsuperbrain` instead",
                "yellow",
            )
        )

    if not pid_file.exists():
        checks.append(("Watcher", "not running", "yellow"))
    elif watcher_pid is None:
        checks.append(("Watcher", "PID file unreadable (run `agsuperbrain stop`)", "red"))
    elif watcher_running:
        checks.append(("Watcher", f"running (PID {watcher_pid})", "green"))
        # If running, surface live queue info from watcher.status.json.
        try:
            import json

            status_path = path / ".agsuperbrain" / "watcher.status.json"
            if status_path.exists():
                data = json.loads(status_path.read_text(encoding=TEXT_ENCODING))
                state = data.get("state") or "unknown"
                pending = data.get("pending_count")
                last_flush = data.get("last_flush_at")
                extra = f"state={state}"
                if pending is not None:
                    extra += f", pending={pending}"
                if last_flush:
                    extra += f", last_flush={last_flush}"
                checks.append(("Watcher queue", extra, "green" if state != "error" else "yellow"))
        except Exception:
            pass
    else:
        checks.append(("Watcher", f"stale PID {watcher_pid} (run `agsuperbrain stop`)", "red"))

    # ── Render ────────────────────────────────────────────────────────────
    t = Table(header_style="bold cyan")
    t.add_column("Check", style="bold")
    t.add_column("Status")
    for name, status, color in checks:
        t.add_row(name, f"[{color}]{status}[/{color}]")
    console.print(t)

    failed = sum(1 for _, _, c in checks if c == "red")
    warned = sum(1 for _, _, c in checks if c == "yellow")
    if failed > 0:
        console.print(f"\n[red]✗ {failed} check(s) failed[/red]", end="")
        if warned:
            console.print(f"  [yellow]({warned} warning(s))[/yellow]")
        else:
            console.print()
        # If any failure is a missing required dep, point at the one-command fix.
        if _find_missing_deps():
            console.print("\n[bold]Fix missing dependencies with:[/bold] [cyan]agsuperbrain repair[/cyan]")
        raise typer.Exit(code=1)
    if warned:
        console.print(f"\n[yellow]{warned} warning(s) — not blocking.[/yellow]")
    else:
        console.print("\n[green]✓ All checks passed[/green]")


@app.command(name="cluster")
def cluster_graph(
    db: Path = typer.Option(_DB, "--db"),
    resolution: float = typer.Option(
        1.0, "--resolution", "-r", help="Leiden resolution (higher = more, smaller communities)"
    ),
    random_state: int = typer.Option(42, "--seed", "-s"),
) -> None:
    """
    Detect communities in the graph using Leiden algorithm.

    Clusters by edge density — no embeddings needed.
    Communities are saved to the graph for later querying.

    Examples:
        superbrain cluster
        superbrain cluster --resolution 1.5
    """
    from agsuperbrain.memory.graph.clustering import cluster

    gs = _store(db)
    gs.init_schema()

    console.rule("[bold cyan]Super-Brain · Community Detection")
    result = cluster(gs, resolution=resolution, random_state=random_state)

    for comm in result.communities:
        gs._create_node(
            "Community",
            {
                "id": f"community_{comm.id}",
                "name": comm.name,
                "size": comm.size,
                "modularity": result.modularity,
            },
        )
        for node_id in comm.nodes:
            gs._merge_edge(
                "Function",
                node_id,
                "Community",
                f"community_{comm.id}",
                "IN_COMMUNITY",
                {"source_path": "clustering"},
            )

    console.print(f"[bold green]✓[/bold green] {len(result.communities)} communities detected")
    console.print(f"[dim]Modularity:[/dim] {result.modularity:.4f}")

    t = Table(title="Communities", header_style="bold cyan")
    t.add_column("ID", justify="right")
    t.add_column("Size", justify="right")
    t.add_column("Sample Nodes", max_width=60)
    for comm in result.communities[:10]:
        sample = ", ".join(comm.nodes[:3])
        t.add_row(str(comm.id), str(comm.size), sample)
    console.print(t)


@app.command(name="export")
def export_graph(
    db: Path = typer.Option(_DB, "--db"),
    output: Path = typer.Option(Path("./graph-export.json"), "--output", "-o"),
) -> None:
    """Export the graph to JSON for portability."""
    from agsuperbrain.memory.graph.graph_store import GraphStore as _GraphStore

    gs = _GraphStore(db)
    gs.init_schema()

    data = {"nodes": [], "edges": []}

    for label in ["Module", "Function", "Document", "Section", "Concept", "AudioSource", "Transcript"]:
        rows = gs.query(f"MATCH (n:{label}) RETURN n")
        for row in rows:
            if row[0]:
                data["nodes"].append({"label": label, **row[0]})

    for rel in ["CALLS", "DEFINED_IN", "CONTAINS", "SOURCE", "FOLLOWS"]:
        rows = gs.query(f"MATCH (a)-[r:{rel}]->(b) RETURN a.id, b.id, r")
        for row in rows:
            if row[0] and row[1]:
                data["edges"].append({"source": row[0], "target": row[1], "relation": rel})

    import json

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2), encoding=TEXT_ENCODING)
    console.print(f"[green]Exported:[/green] {len(data['nodes'])} nodes, {len(data['edges'])} edges")


@app.command(name="import")
def import_graph(
    input: Path = typer.Argument(...),
    db: Path = typer.Option(_DB, "--db"),
) -> None:
    """Import graph from JSON export."""
    import json

    from agsuperbrain.memory.graph.graph_store import GraphStore as _GraphStore

    data = json.loads(input.read_text(encoding=TEXT_ENCODING))

    gs = _GraphStore(db)
    gs.init_schema()

    for node in data.get("nodes", []):
        label = node.pop("label", "Function")
        gs._create_node(label, node)

    for edge in data.get("edges", []):
        src, tgt = edge.get("source"), edge.get("target")
        rel = edge.get("relation", "CALLS")
        if src and tgt:
            gs._merge_edge("Function", src, "Function", tgt, rel, {})

    console.print(f"[green]Imported:[/green] {len(data.get('nodes', []))} nodes")


def _build_tools(db, qdrant_path, no_llm=False):
    from agsuperbrain.intelligence.context_builder import ContextBuilder
    from agsuperbrain.intelligence.llm_engine import get_llm_engine
    from agsuperbrain.intelligence.retriever import HybridRetriever
    from agsuperbrain.intelligence.tools import SuperBrainTools
    from agsuperbrain.memory.graph.graph_store import GraphStore
    from agsuperbrain.memory.vector.embedder import TextEmbedder
    from agsuperbrain.memory.vector.vector_store import VectorStore

    gs = GraphStore(db)
    gs.init_schema()
    vs = VectorStore(db_path=qdrant_path)
    emb = TextEmbedder()
    ret = HybridRetriever(gs, vs, emb)
    cb = ContextBuilder()

    llm = None
    if not no_llm:
        llm = get_llm_engine()

    return SuperBrainTools(ret, cb, llm_engine=llm)


@app.command(name="ask")
def ask(
    query: str = typer.Argument(...),
    mode: str = typer.Option("all", "--mode", "-m"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    json_output: bool = typer.Option(False, "--json"),
    no_llm: bool = typer.Option(False, "--no-llm"),
    db: Path = typer.Option(_DB, "--db"),
    qdrant_path: Path = typer.Option(_QDRANT, "--qdrant-path"),
) -> None:
    tools = _build_tools(db, qdrant_path, no_llm)
    tools.top_k = top_k
    dispatch = {
        "all": tools.search,
        "code": tools.code_tool,
        "audio": tools.audio_tool,
        "document": tools.document_tool,
    }
    resp = dispatch.get(mode, tools.search)(query)

    if json_output:
        console.print(resp.to_json())
        return

    console.rule("[bold cyan]Super-Brain Answer")
    console.print(f"\n[bold]{resp.answer}[/bold]\n")
    console.print(f"[dim]LLM used:[/dim] {'yes' if resp.used_llm else 'no (deterministic)'}")

    t = Table(title="Evidence", header_style="bold cyan")
    t.add_column("Score", justify="right")
    t.add_column("Hops", justify="right")
    t.add_column("Type", justify="left")
    t.add_column("Text", justify="left")
    t.add_column("Source", justify="left")
    for e in resp.evidence:
        if e.get("is_stub"):
            continue  # hide stubs from table
        t.add_row(
            str(e["score"]),
            str(e["graph_hops"]),
            e["node_type"],
            e["text"][:80],
            e["source_path"].split("/")[-1] if e["source_path"] else "",
        )
    console.print(t)
    console.print(f"\n[dim]Confidence:[/dim] [bold]{resp.confidence:.0%}[/bold]")


@app.command(name="mcp")
@app.command(name="mcp-serve")
def mcp_serve() -> None:
    """
    Start MCP server (stdio mode) for IDE/agent integration.

    This exposes Super-Brain tools via stdio JSON-RPC, compatible with:
    - Claude Code
    - Cursor
    - Aider
    - OpenCode
    - Cline
    - Continue

    Example configuration:

    Claude Code:
      Create ~/.claude/settings.json with:
      {
        "mcpServers": {
          "agsuperbrain": {
            "command": "python",
            "args": ["-m", "agsuperbrain", "mcp"]
          }
        }
      }

    Cursor:
      Add to ~/.cursor/mcp.json:
      {
        "mcpServers": {
          "agsuperbrain": {
            "type": "stdio",
            "command": "python",
            "args": ["-m", "agsuperbrain", "mcp"]
          }
        }
      }
    """
    from agsuperbrain.mcp.server import main

    main()


@app.command(name="print-mcp-config")
def print_mcp_config(
    ide: str = typer.Option(
        "cursor",
        "--ide",
        help="Output shape: cursor (type stdio) or claude (command/args only).",
    ),
) -> None:
    """
    Print a ready-to-paste mcp.json snippet for the current Python (see sys.executable).

    Use this when Cursor does not see `agsuperbrain` on PATH — the JSON uses
    `python -m agsuperbrain mcp` with an absolute interpreter path, same as
    `agsuperbrain cursor-install` writes to .cursor/mcp.json.

    Examples:
        agsuperbrain print-mcp-config
        agsuperbrain print-mcp-config --ide claude
    """
    import json

    if ide not in ("cursor", "claude"):
        raise typer.BadParameter("Use --ide cursor or --ide claude.")
    entry = _mcp_server_config_for_cursor() if ide == "cursor" else _mcp_server_config()
    cfg = {"mcpServers": {"agsuperbrain": entry}}
    # Plain stdout for reliable copy-paste (no Rich styling).
    sys.stdout.write(json.dumps(cfg, indent=2) + "\n")


def _detect_source_dir(project: Path) -> Path | None:
    """Return the project root as the default ingest target.

    The extraction pipeline already skips the standard noise directories
    (.venv, node_modules, __pycache__, .git, dist, build, .tox, etc.)
    via the default exclude list, so scanning from the project root is
    safe for any layout — flat Python, src-layout Python, Maven/Gradle/
    Spring Boot (src/main/java/...), Go (cmd/, internal/, pkg/), Rust
    crates, .NET per-project folders, Rails, Flutter (lib/), Swift
    (Sources/), Unity, Unreal, and monorepos. Returns None only if the
    project directory doesn't exist.
    """
    return project if project.is_dir() else None


@app.command(name="init")
def init(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory to initialize"),
    src: Path | None = typer.Option(
        None,
        "--src",
        help="Specific source directory to ingest. Default: the whole "
        "project (standard noise like .venv, node_modules, .git, "
        "dist, build is excluded automatically). Useful for "
        "monorepos: --src ./services/api",
    ),
    skip_ingest: bool = typer.Option(
        False,
        "--skip-ingest",
        help="Skip the initial ingest + index-vectors pass",
    ),
) -> None:
    """
    Initialize Super-Brain in the current project.

    Performs, in order:
      1. Writes .agsuperbrain/config.yaml, .agsuperbrainignore, and updates
         .gitignore
      2. Runs `ingest` + `index-vectors` on the project root (or the path
         given by --src). The pipeline already excludes .venv, node_modules,
         __pycache__, .git, dist, build, etc., so this works for any
         layout — flat, src-layout, Maven/Gradle, Go, Rust, .NET, Rails,
         Flutter, monorepos, and so on.
      3. Starts the background file watcher so subsequent edits are
         incrementally re-indexed

    Examples:
        agsuperbrain init
        agsuperbrain init --path ./my-project
        agsuperbrain init --src ./services/api       # monorepo: one workspace
        agsuperbrain init --skip-ingest              # config only; ingest later
    """
    _do_full_init(path, src=src, skip_ingest=skip_ingest, show_next_steps=True)


# ── Platform-specific install commands ──────────────────────────────────


@app.command(name="claude-install")
def install_claude(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory"),
) -> None:
    """
    Install always-on integration for Claude Code.

    Creates:
      - .claude/settings.json with PreToolUse hook
      - AGENTS.md with always-on rules
      - MCP server configuration

    Auto-initializes if not already done.

    This makes Claude Code automatically use the knowledge graph
    before every file search - no need to explicitly invoke.

    Example:
        agsuperbrain claude install
    """
    _ensure_initialized(path)

    import json

    console.rule("[bold cyan]Super-Brain · Claude Code Integration")

    # 1. Create CLAUDE.md rules (global)
    claude_md = path / "CLAUDE.md"
    rules_content = """# Super-Brain Knowledge Graph

You have access to a Super-Brain knowledge graph in this project.

When answering architecture questions:
1. Check if a knowledge graph exists: .agsuperbrain/graph/
2. If it exists, query it first instead of searching raw files
3. Use AGENTS.md for context about the codebase

Commands:
- agsuperbrain ask "question" - Query the graph
- agsuperbrain visualize - Open interactive graph
"""
    if claude_md.exists():
        content = claude_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            claude_md.write_text(content + "\n\n" + rules_content, encoding=TEXT_ENCODING)
            console.print("[green]Updated:[/green] CLAUDE.md")
    else:
        claude_md.write_text(rules_content, encoding=TEXT_ENCODING)
        console.print("[green]Created:[/green] CLAUDE.md")

    # 2. Create AGENTS.md
    agents_md = path / "AGENTS.md"
    agent_rules = """# Super-Brain Agent Rules

## Always-On Context
- Read .agsuperbrain/graph/ for knowledge graph
- Query graph before searching raw files for architecture questions

## Tools
Use `agsuperbrain` CLI for:
- Semantic search: agsuperbrain search-vectors "query"
- Ask questions: agsuperbrain ask "question"
- Visualize: agsuperbrain visualize

## Graph Tips
- God nodes = most called functions (entry points)
- Call chains show dependencies
- Communities show related code groups
"""
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(content + "\n\n" + agent_rules, encoding=TEXT_ENCODING)
            console.print("[green]Updated:[/green] AGENTS.md")
    else:
        agents_md.write_text(agent_rules, encoding=TEXT_ENCODING)
        console.print("[green]Created:[/green] AGENTS.md")

    # 3. Settings: MCP server registration + PreToolUse hook
    settings_file = path / ".claude" / "settings.json"
    settings_file.parent.mkdir(exist_ok=True)

    current_settings: dict = {} if not settings_file.exists() else json.loads(settings_file.read_text(encoding=TEXT_ENCODING))

    # MCP server entry — lets Claude Code actually CALL the Super-Brain
    # tools (search_code, find_callers, etc.) rather than just read rule
    # text about them. Uses sys.executable -m agsuperbrain so it works
    # regardless of whether the `agsuperbrain` script is on Claude's PATH.
    current_settings.setdefault("mcpServers", {})["agsuperbrain"] = _mcp_server_config()

    # PreToolUse hook — nudges Claude toward the graph before raw file
    # searches. Kept in addition to the rule files for belt-and-braces.
    if "hooks" not in current_settings:
        current_settings["hooks"] = {}
    if "PreToolUse" not in current_settings["hooks"]:
        current_settings["hooks"]["PreToolUse"] = {
            "type": "command",
            "command": "bash",
            "arguments": [
                "-c",
                '[ -f .agsuperbrain/graph/superbrain.db ] && echo \'{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"Super-Brain: Knowledge graph exists. Use agsuperbrain ask or search-vectors before raw file searches."}}\' || echo \'\'',
            ],
        }
    else:
        console.print("[dim]PreToolUse hook already exists[/dim]")

    settings_file.write_text(json.dumps(current_settings, indent=2), encoding=TEXT_ENCODING)
    console.print(f"[green]Wrote:[/green] {settings_file} (MCP server + PreToolUse hook)")

    # Post-install check: verify agsuperbrain is importable
    success, error = _check_mcp_installed()
    if not success:
        console.print(
            f"\n[yellow]Warning: agsuperbrain not importable.[/yellow]\n"
            f"[yellow]Error: {error}[/yellow]\n"
            f"\n[cyan]Fix:[/cyan] Install with:\n"
            f"  pip install agsuperbrain\n"
            f"  # or in your venv:\n"
            f"  source your-venv/bin/activate && pip install agsuperbrain"
        )

    # .claude/settings.json now contains a machine-specific MCP server
    # command. Keep it out of version control.
    _gitignore_add(path, [".claude/settings.json"])

    console.print("\n[bold green]✓[/bold green] Claude Code integration installed")
    _mcp_config_portability_note()
    console.print("[dim]Restart Claude Code once so it picks up the new MCP server.[/dim]")


@app.command(name="claude-uninstall")
def uninstall_claude(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Remove Claude Code always-on integration."""

    files_to_remove = [
        path / "CLAUDE.md",
        path / "AGENTS.md",
    ]

    for f in files_to_remove:
        if f.exists():
            f.unlink()
            console.print(f"[yellow]Removed:[/yellow] {f.name}")

    # Keep MCP config but remove hooks
    settings_file = path / ".claude" / "settings.json"
    if settings_file.exists():
        import json

        settings = json.loads(settings_file.read_text(encoding=TEXT_ENCODING))
        if "hooks" in settings:
            del settings["hooks"]
            settings_file.write_text(json.dumps(settings, indent=2), encoding=TEXT_ENCODING)
            console.print("[yellow]Removed:[/yellow] hooks from settings.json")

    console.print("[green]Claude Code integration removed[/green]")


@app.command(name="cursor-install")
def install_cursor(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """
    Install always-on integration for Cursor.

    Creates two files:
      - .cursor/rules/superbrain.mdc — always-on system prompt ("the graph
        exists; use it before raw file searches")
      - .cursor/mcp.json — MCP server registration so Cursor's assistant
        can actually CALL the Super-Brain tools (search_code, find_callers,
        path_between, ...), not just read about them.

    Auto-initializes the project if not already done.

    Example:
        agsuperbrain cursor-install
    """
    _ensure_initialized(path)

    import json

    console.rule("[bold cyan]Super-Brain · Cursor Integration")

    # 1. Rules file — system-prompt context injection.
    rules_dir = path / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rules_file = rules_dir / "superbrain.mdc"
    rules_content = """# Super-Brain Knowledge Graph

Always apply this rule: use the Super-Brain MCP tools for architecture questions
instead of raw file searches.

Available MCP tools (registered via .cursor/mcp.json):
- search_code(query, limit, mode)      semantic code search
- find_callers(function_id)            who calls this function
- find_callees(function_id)            what this function calls
- get_function_body(qualified_name)    signature, docstring, source
- path_between(src_id, dst_id)         call path from A to B
- closure(node_id, relation, max_hops) transitive closure
- get_subgraph(root_id, depth)         local neighbourhood
- stats / list_modules / list_functions

Read .agsuperbrain/GRAPH_REPORT.md for a human summary of the graph state.
"""
    if rules_file.exists():
        content = rules_file.read_text(encoding=TEXT_ENCODING)
        if "Super-Brain" not in content:
            rules_file.write_text(content + "\n\n" + rules_content, encoding=TEXT_ENCODING)
            console.print(f"[green]Updated:[/green] {rules_file}")
        else:
            # Always overwrite — keeps the rule content in sync with the
            # current MCP tool list.
            rules_file.write_text(rules_content, encoding=TEXT_ENCODING)
            console.print(f"[green]Refreshed:[/green] {rules_file}")
    else:
        rules_file.write_text(rules_content, encoding=TEXT_ENCODING)
        console.print(f"[green]Created:[/green] {rules_file}")

    # 2. MCP server registration — so Cursor can actually invoke the tools.
    mcp_file = path / ".cursor" / "mcp.json"
    mcp_config = {"mcpServers": {"agsuperbrain": _mcp_server_config_for_cursor()}}

    if mcp_file.exists():
        try:
            existing = json.loads(mcp_file.read_text(encoding=TEXT_ENCODING))
        except json.JSONDecodeError:
            existing = {}
        existing.setdefault("mcpServers", {})["agsuperbrain"] = _mcp_server_config_for_cursor()
        mcp_file.write_text(json.dumps(existing, indent=2), encoding=TEXT_ENCODING)
        console.print(f"[green]Updated:[/green] {mcp_file}")
    else:
        mcp_file.write_text(json.dumps(mcp_config, indent=2), encoding=TEXT_ENCODING)
        console.print(f"[green]Created:[/green] {mcp_file}")

    # Keep the machine-specific MCP config out of version control so a
    # teammate or CI runner on a different OS doesn't inherit a broken path.
    _gitignore_add(path, [".cursor/mcp.json"])

    # Post-install check: verify agsuperbrain is importable
    success, error = _check_mcp_installed()
    if not success:
        console.print(
            f"\n[yellow]Warning: agsuperbrain not importable.[/yellow]\n"
            f"[yellow]Error: {error}[/yellow]\n"
            f"\n[cyan]Fix:[/cyan] Install with:\n"
            f"  pip install agsuperbrain\n"
            f"  # or in your venv:\n"
            f"  source your-venv/bin/activate && pip install agsuperbrain"
        )

    console.print("\n[bold green]✓[/bold green] Cursor integration installed")
    _mcp_config_portability_note()
    console.print("[dim]Restart Cursor once so it picks up the new MCP server.[/dim]")


@app.command(name="cursor-uninstall")
def uninstall_cursor(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Remove Cursor always-on integration."""

    rules_file = path / ".cursor" / "rules" / "superbrain.mdc"
    if rules_file.exists():
        rules_file.unlink()
        console.print(f"[yellow]Removed:[/yellow] {rules_file.name}")
    else:
        console.print("[dim]No Cursor rules found[/dim]")


@app.command(name="aider-install")
def install_aider(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """
    Install always-on for Aider.

    Updates .aider.conf.yml with MCP server.
    Auto-initializes if not already done.

    Example:
        agsuperbrain aider install
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Aider Integration")

    import sys

    conf_file = path / ".aider.conf.yml"
    # Aider expects an MCP server list. Using `sys.executable -m agsuperbrain`
    # so the invocation is PATH-independent.
    mcp_block = (
        "\n# Super-Brain — added by `agsuperbrain aider-install`\n"
        "mcp-servers:\n"
        "  - name: agsuperbrain\n"
        f"    command: {sys.executable}\n"
        "    args:\n"
        "      - -m\n"
        "      - agsuperbrain\n"
        "      - mcp-serve\n"
    )

    if conf_file.exists():
        content = conf_file.read_text(encoding=TEXT_ENCODING)
        if "agsuperbrain" not in content:
            conf_file.write_text(content.rstrip() + "\n" + mcp_block, encoding=TEXT_ENCODING)
            console.print(f"[green]Updated:[/green] {conf_file}")
        else:
            console.print(f"[dim]Already configured:[/dim] {conf_file}")
    else:
        conf_file.write_text(mcp_block.lstrip(), encoding=TEXT_ENCODING)
        console.print(f"[green]Created:[/green] {conf_file}")

    # Aider conf is typically committed; we DON'T auto-gitignore it, but
    # the portability note tells the user to re-run per machine.
    _mcp_config_portability_note()

    # Also create AGENTS.md for always-on
    agents_file = path / "AGENTS.md"
    agents_content = """# Super-Brain for Aider

## Always-On
Use the Super-Brain knowledge graph:

- `agsuperbrain ask "question"` - Query graph
- `agsuperbrain search-vectors "query"` - Semantic search

Query graph before searching files for architecture context.
"""

    if agents_file.exists():
        content = agents_file.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_file.write_text(content + "\n\n" + agents_content, encoding=TEXT_ENCODING)
            console.print("[green]Updated:[/green] AGENTS.md")
    else:
        agents_file.write_text(agents_content, encoding=TEXT_ENCODING)
        console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] Aider always-on installed")


@app.command(name="aider-uninstall")
def uninstall_aider(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Remove Aider always-on integration."""

    conf_file = path / ".aider.conf.yml"
    if conf_file.exists():
        lines = [line for line in conf_file.read_text(encoding=TEXT_ENCODING).splitlines() if "agsuperbrain" not in line]
        conf_file.write_text("\n".join(lines) + "\n", encoding=TEXT_ENCODING)
        console.print("[yellow]Removed Super-Brain from:[/yellow] .aider.conf.yml")


# ── Additional Platform Install Commands ────────────────────────────────────────


@app.command(name="codex-install")
def install_codex(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """
    Install always-on for OpenAI Codex.

    Creates AGENTS.md and PreToolUse hook.
    Auto-initializes if not already done.

    Example:
        agsuperbrain codex install
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Codex Integration")

    agents_md = path / "AGENTS.md"
    agents_content = """# Super-Brain for Codex

Always consult the knowledge graph for architecture questions.

Commands:
- agsuperbrain ask "question"
- agsuperbrain search-vectors "query"

Query .agsuperbrain/graph/ first for context.
"""
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(content + "\n\n" + agents_content, encoding=TEXT_ENCODING)
            console.print("[green]Updated:[/green] AGENTS.md")
    else:
        agents_md.write_text(agents_content, encoding=TEXT_ENCODING)
        console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] Codex always-on installed")


@app.command(name="opencode-install")
def install_opencode(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """
    Install always-on for OpenCode.

    Creates AGENTS.md and plugin.
    Auto-initializes if not already done.

    Example:
        agsuperbrain opencode install
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · OpenCode Integration")

    agents_md = path / "AGENTS.md"
    agents_content = """# Super-Brain for OpenCode

Always consult the knowledge graph for architecture questions.

Commands:
- agsuperbrain ask "question"
- agsuperbrain search-vectors "query"
"""
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(content + "\n\n" + agents_content, encoding=TEXT_ENCODING)
    else:
        agents_md.write_text(agents_content, encoding=TEXT_ENCODING)
        console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] OpenCode always-on installed")


@app.command(name="copilot-install")
def install_copilot(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """
    Install for GitHub Copilot CLI.
    Auto-initializes if not already done.

    Example:
        agsuperbrain copilot install
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · GitHub Copilot CLI")

    # Create skill file
    skill_dir = Path.home() / ".copilot" / "skills" / "superbrain"
    skill_dir.parent.mkdir(parents=True, exist_ok=True)

    skill_content = """# Super-Brain Skill

Query the Super-Brain knowledge graph using:
- agsuperbrain ask "question"
- agsuperbrain search-vectors "query"

This provides context about code architecture, dependencies, and communities.
"""
    skill_file = skill_dir / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(skill_content, encoding=TEXT_ENCODING)
    console.print(f"[green]Created:[/green] {skill_file}")

    console.print("\n[bold green]✓[/bold green] GitHub Copilot CLI installed")


@app.command(name="vscode-install")
def install_vscode(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """
    Install for VS Code Copilot Chat.

    Creates .github/copilot-instructions.md.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · VS Code Copilot")

    instructions = path / ".github" / "copilot-instructions.md"
    instructions.parent.mkdir(parents=True, exist_ok=True)

    content = """# Super-Brain Context

Use agsuperbrain CLI for knowledge graph queries:
- agsuperbrain ask "question"
- agsuperbrain search-vectors "query"

This provides architecture context before file searches.
"""
    instructions.write_text(content, encoding=TEXT_ENCODING)
    console.print(f"[green]Created:[/green] {instructions}")

    console.print("\n[bold green]✓[/bold green] VS Code Copilot installed")


@app.command(name="openclaw-install")
def install_openclaw(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for OpenClaw.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · OpenClaw")

    agents_md = path / "AGENTS.md"
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(
                content + "\n\n# Super-Brain for OpenClaw\nUse agsuperbrain ask for architecture context.",
                encoding=TEXT_ENCODING,
            )
    else:
        agents_md.write_text(
            "# Super-Brain for OpenClaw\nUse agsuperbrain ask for architecture context.",
            encoding=TEXT_ENCODING,
        )
    console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] OpenClaw installed")


@app.command(name="droid-install")
def install_droid(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for Factory Droid.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Factory Droid")

    agents_md = path / "AGENTS.md"
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(
                content + "\n\n# Super-Brain for Factory Droid\nUse agsuperbrain ask for context.",
                encoding=TEXT_ENCODING,
            )
    else:
        agents_md.write_text(
            "# Super-Brain for Factory Droid\nUse agsuperbrain ask for context.",
            encoding=TEXT_ENCODING,
        )
    console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] Factory Droid installed")


@app.command(name="trae-install")
def install_trae(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for Trae AI.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Trae")

    agents_md = path / "AGENTS.md"
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(
                content + "\n\n# Super-Brain for Trae\nUse agsuperbrain ask for architecture context.",
                encoding=TEXT_ENCODING,
            )
    else:
        agents_md.write_text(
            "# Super-Brain for Trae\nUse agsuperbrain ask for architecture context.",
            encoding=TEXT_ENCODING,
        )
    console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] Trae installed")


@app.command(name="gemini-install")
def install_gemini(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for Gemini CLI.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    import json

    console.rule("[bold cyan]Super-Brain · Gemini CLI")

    # Create AGENTS.md
    agents_md = path / "AGENTS.md"
    agents_content = """# Super-Brain for Gemini CLI

Use agsuperbrain CLI for architecture queries:
- agsuperbrain ask "question"
- agsuperbrain search-vectors "query"
"""
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(content + "\n\n" + agents_content, encoding=TEXT_ENCODING)
    else:
        agents_md.write_text(agents_content, encoding=TEXT_ENCODING)
    console.print("[green]Created:[/green] AGENTS.md")

    # Create .gemini/settings.json with BeforeTool hook
    gemini_dir = path / ".gemini"
    gemini_dir.mkdir(exist_ok=True)
    settings_file = gemini_dir / "settings.json"

    # Both an MCP server registration (so Gemini can call Super-Brain tools
    # directly) and a BeforeTool hook (context injection before file reads).
    new_settings: dict = {
        "mcpServers": {"agsuperbrain": _mcp_server_config()},
        "hooks": {
            "BeforeTool": {
                "type": "command",
                "command": "bash",
                "arguments": [
                    "-c",
                    "[ -f .agsuperbrain/graph/superbrain.db ] && "
                    "echo 'Super-Brain: Use agsuperbrain ask before file reads.' || echo ''",
                ],
            }
        },
    }

    if settings_file.exists():
        existing = json.loads(settings_file.read_text(encoding=TEXT_ENCODING))
        existing.setdefault("mcpServers", {})["agsuperbrain"] = _mcp_server_config()
        existing.setdefault("hooks", {}).update(new_settings["hooks"])
        settings_file.write_text(json.dumps(existing, indent=2), encoding=TEXT_ENCODING)
    else:
        settings_file.write_text(json.dumps(new_settings, indent=2), encoding=TEXT_ENCODING)

    console.print(f"[green]Wrote:[/green] {settings_file} (MCP server + BeforeTool hook)")

    _gitignore_add(path, [".gemini/settings.json"])

    console.print("\n[bold green]✓[/bold green] Gemini CLI integration installed")
    _mcp_config_portability_note()
    console.print("[dim]Restart Gemini CLI once so it picks up the new MCP server.[/dim]")


@app.command(name="hermes-install")
def install_hermes(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for Hermes AI.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Hermes")

    # Create global skill
    skill_dir = Path.home() / ".hermes" / "skills" / "superbrain"
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """# Super-Brain Skill

Use agsuperbrain ask "question" to query the knowledge graph.
Use agsuperbrain search-vectors "query" for semantic search.
""",
        encoding=TEXT_ENCODING,
    )
    console.print(f"[green]Created:[/green] {skill_file}")

    # Create AGENTS.md
    agents_md = path / "AGENTS.md"
    if agents_md.exists():
        content = agents_md.read_text(encoding=TEXT_ENCODING)
        if "# Super-Brain" not in content:
            agents_md.write_text(content + "\n\n# Super-Brain for Hermes\nUse agsuperbrain ask.", encoding=TEXT_ENCODING)
    else:
        agents_md.write_text("# Super-Brain for Hermes\nUse agsuperbrain ask.", encoding=TEXT_ENCODING)
    console.print("[green]Created:[/green] AGENTS.md")

    console.print("\n[bold green]✓[/bold green] Hermes installed")


@app.command(name="kiro-install")
def install_kiro(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for Kiro IDE.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Kiro")

    # Create skill
    skill_dir = path / ".kiro" / "skills" / "superbrain"
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """# Super-Brain Skill

Invoke via /superbrain command.
Use agsuperbrain ask for architecture questions.
""",
        encoding=TEXT_ENCODING,
    )
    console.print(f"[green]Created:[/green] {skill_file}")

    # Create steering file
    steering_dir = path / ".kiro" / "steering"
    steering_dir.mkdir(parents=True, exist_ok=True)

    steering_file = steering_dir / "superbrain.md"
    steering_file.write_text(
        """# Super-Brain Steering

inclusion: always
""",
        encoding=TEXT_ENCODING,
    )
    console.print(f"[green]Created:[/green] {steering_file}")

    console.print("\n[bold green]✓[/bold green] Kiro installed")


@app.command(name="antigravity-install")
def install_antigravity(
    path: Path = typer.Option(Path("."), "--path", "-p"),
) -> None:
    """Install for Google Antigravity.
    Auto-initializes if not already done.
    """
    _ensure_initialized(path)

    console.rule("[bold cyan]Super-Brain · Google Antigravity")

    # Create agent rules
    rules_dir = path / ".agent" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    rules_file = rules_dir / "superbrain.md"
    rules_file.write_text(
        """# Super-Brain Agent Rules

Always apply:
- Use agsuperbrain ask "question" to query the knowledge graph
- Use agsuperbrain search-vectors "query" for semantic search

This provides architecture context before file operations.
""",
        encoding=TEXT_ENCODING,
    )
    console.print(f"[green]Created:[/green] {rules_file}")

    # Create workflows
    workflow_dir = path / ".agent" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    workflow_file = workflow_dir / "superbrain.md"
    workflow_file.write_text(
        """# Super-Brain Workflows

Commands:
- /superbrain ask "question"
- /superbrain search "query"
- /superbrain visualize
""",
        encoding=TEXT_ENCODING,
    )
    console.print(f"[green]Created:[/green] {workflow_file}")

    console.print("\n[bold green]✓[/bold green] Google Antigravity installed")


# ── Unified install command ────────────────────────────────────────────────


@app.command(name="install")
def install_all(
    platform: str = typer.Option(
        "all",
        "--platform",
        "-p",
        help="Platform: all, claude, cursor, aider, codex, opencode, vscode, openclaw, droid, trae, gemini, hermes, kiro, antigravity",
    ),
    path: Path = typer.Option(Path("."), "--path"),
) -> None:
    """
    Install Super-Brain for specific platform(s).

    Examples:
        agsuperbrain install                    # Show help
        agsuperbrain install all               # Install all platforms
        agsuperbrain install claude            # Claude Code
        agsuperbrain install cursor             # Cursor
        agsuperbrain install aider              # Aider

    Supported platforms: all, claude, cursor, aider, codex, opencode, vscode, openclaw, droid, trae, gemini, hermes, kiro, antigravity
    """
    platform = platform.lower()

    if platform == "all":
        console.print("[bold]Installing all platforms...[/bold]\n")

    installed = []

    if platform == "all" or platform == "claude":
        try:
            install_claude(path)
            installed.append("claude")
        except Exception as e:
            console.print(f"[red]Claude install failed: {e}[/red]")

    if platform == "all" or platform == "cursor":
        try:
            install_cursor(path)
            installed.append("cursor")
        except Exception as e:
            console.print(f"[red]Cursor install failed: {e}[/red]")

    if platform == "all" or platform == "aider":
        try:
            install_aider(path)
            installed.append("aider")
        except Exception as e:
            console.print(f"[red]Aider install failed: {e}[/red]")

    if platform == "all" or platform == "codex":
        try:
            install_codex(path)
            installed.append("codex")
        except Exception as e:
            console.print(f"[red]Codex install failed: {e}[/red]")

    if platform == "all" or platform == "opencode":
        try:
            install_opencode(path)
            installed.append("opencode")
        except Exception as e:
            console.print(f"[red]OpenCode install failed: {e}[/red]")

    if platform == "all" or platform == "vscode":
        try:
            install_vscode(path)
            installed.append("vscode")
        except Exception as e:
            console.print(f"[red]VSCode install failed: {e}[/red]")

    if platform == "all" or platform == "openclaw":
        try:
            install_openclaw(path)
            installed.append("openclaw")
        except Exception as e:
            console.print(f"[red]OpenClaw install failed: {e}[/red]")

    if platform == "all" or platform == "droid":
        try:
            install_droid(path)
            installed.append("droid")
        except Exception as e:
            console.print(f"[red]Factory Droid install failed: {e}[/red]")

    if platform == "all" or platform == "trae":
        try:
            install_trae(path)
            installed.append("trae")
        except Exception as e:
            console.print(f"[red]Trae install failed: {e}[/red]")

    if platform == "all" or platform == "gemini":
        try:
            install_gemini(path)
            installed.append("gemini")
        except Exception as e:
            console.print(f"[red]Gemini CLI install failed: {e}[/red]")

    if platform == "all" or platform == "hermes":
        try:
            install_hermes(path)
            installed.append("hermes")
        except Exception as e:
            console.print(f"[red]Hermes install failed: {e}[/red]")

    if platform == "all" or platform == "kiro":
        try:
            install_kiro(path)
            installed.append("kiro")
        except Exception as e:
            console.print(f"[red]Kiro install failed: {e}[/red]")

    if platform == "all" or platform == "antigravity":
        try:
            install_antigravity(path)
            installed.append("antigravity")
        except Exception as e:
            console.print(f"[red]Google Antigravity install failed: {e}[/red]")

    if installed:
        console.rule("[bold green]Installation Complete")
        console.print(f"[green]Installed: {', '.join(installed)}[/green]")
