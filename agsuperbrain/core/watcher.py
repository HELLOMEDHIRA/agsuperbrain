"""
Incremental re-index on file changes via `watchfiles` (Rust `notify`).

Status snapshots go to `.agsuperbrain/watcher.status.json` for `watch-status`.
On NFS/SMB or similar, use `agsuperbrain watch --use-poll` if native events fail.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from watchfiles import Change, DefaultFilter, watch

from agsuperbrain.analytics.report import generate_report
from agsuperbrain.core.pipeline import CodeGraphPipeline
from agsuperbrain.memory.graph.graph_store import GraphStore
from agsuperbrain.memory.graph.visualizer import visualize as viz
from agsuperbrain.memory.vector.vector_store import VectorStore
from agsuperbrain.terminal import TEXT_ENCODING, console

_CODE_SUFFIXES: frozenset[str] = frozenset((".py", ".js", ".ts", ".mjs"))


# ── Helpers ──────────────────────────────────────────────────────────────────


def _utc_iso(ts: float | None = None) -> str:
    t = time.time() if ts is None else float(ts)
    return datetime.fromtimestamp(t, tz=UTC).isoformat()


def _norm(p: Path) -> Path:
    try:
        return p.resolve()
    except OSError:
        return p


def _find_project_root(anchor: Path) -> Path:
    """Walk up looking for `.agsuperbrain/`, fall back to `.git/`, then `cwd()`."""
    try:
        base = anchor.resolve()
    except OSError:
        base = anchor
    cur = base if base.is_dir() else base.parent
    for _ in range(64):
        if (cur / ".agsuperbrain").exists():
            return cur
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path.cwd()


# ── watchfiles filter ────────────────────────────────────────────────────────


class _CodeFilter(DefaultFilter):
    """Only emit events for known code suffixes; drop noise dirs.

    Subclasses watchfiles' `DefaultFilter`, which already excludes the usual
    suspects (`.git`, `__pycache__`, `node_modules`, `.venv`, virtualenvs,
    common IDE dirs). We add Super-Brain's own data dir and the code-suffix
    allowlist on top.
    """

    def __init__(self, exclude_dirs: frozenset[str]) -> None:
        super().__init__()
        # Always exclude our own data/output trees so writes to graph.html
        # or status.json don't trigger watcher loops.
        self._extra_excluded_dirs: frozenset[str] = exclude_dirs | frozenset(
            {
                ".agsuperbrain",
                "output",
            }
        )

    def __call__(self, change: Change, path: str) -> bool:
        if not super().__call__(change, path):
            return False
        p = Path(path)
        # Drop anything inside an excluded directory at any depth.
        if any(part in self._extra_excluded_dirs for part in p.parts):
            return False
        # Code-only allowlist; directory events pass through to children.
        suf = p.suffix.lower()
        return not suf or suf in _CODE_SUFFIXES


# ── Watcher ──────────────────────────────────────────────────────────────────


class FileWatcher:
    """
    Watch directories for code changes and re-index incrementally.

    Constructor and public-method signatures are kept backward-compatible
    with the previous watchdog-based implementation so the `watch` CLI
    command and `_start_watcher_background` keep working without changes.

    Usage::

        watcher = FileWatcher(graph_store, vector_store, [Path("./src")])
        watcher.start(debounce=0.4)            # blocks until Ctrl+C / stop()
        # or
        watcher.run_once()                      # single hash-scan + reindex
    """

    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore,
        watch_paths: list[Path],
        exclude_dirs: frozenset[str] | None = None,
    ) -> None:
        self.gs = graph_store
        self.vs = vector_store
        self.watch_paths = watch_paths
        self.exclude_dirs = exclude_dirs or frozenset()
        self.project_root = _find_project_root(watch_paths[0] if watch_paths else Path.cwd())
        self._status_path = (self.project_root / ".agsuperbrain" / "watcher.status.json").resolve()
        self._pipeline = CodeGraphPipeline(graph_store, vector_store)
        self._stop_event = Event()
        self._text_embedder = None  # lazy init — sentence-transformers is heavy

        # Diagnostic state
        self._last_flush_at: str | None = None
        self._last_indexed: list[str] = []
        self._last_error: str | None = None
        self._last_heartbeat_at: str = _utc_iso()
        self._batches_processed: int = 0
        self._files_processed: int = 0
        self._current_batch: set[Path] = set()

        try:
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._write_status(state="idle")

    # ── status JSON ──────────────────────────────────────────────────────────

    def _write_status(self, *, state: str) -> None:
        """Atomic best-effort status snapshot. Never raises out."""
        try:
            try:
                from importlib.metadata import version

                agsb_version = version("agsuperbrain")
            except Exception:
                agsb_version = None
            payload = {
                "state": state,
                "pid": os.getpid(),
                "agsuperbrain_version": agsb_version,
                "watcher_source_file": str(Path(__file__).resolve()),
                "project_root": str(self.project_root),
                "watch_paths": [str(p) for p in self.watch_paths],
                "backend": "watchfiles",
                # Old-name aliases — keeps `watch-status` and the doc strings
                # that key off `pending_count` / `pending_paths` working.
                "pending_count": len(self._current_batch),
                "pending_paths": sorted({str(p) for p in self._current_batch})[:25],
                # New canonical fields (same data, clearer names).
                "current_batch_size": len(self._current_batch),
                "current_batch_paths": sorted({str(p) for p in self._current_batch})[:25],
                "last_flush_at": self._last_flush_at,
                "last_heartbeat_at": self._last_heartbeat_at,
                "last_indexed_paths": self._last_indexed[:25],
                "last_error": self._last_error,
                "batches_processed": self._batches_processed,
                "files_processed": self._files_processed,
                # `worker_alive` is meaningful here — while the watcher process
                # is running this loop, the "worker" (us) is by definition
                # alive. Stale heartbeat is the real death signal; the
                # `watch-status` command checks heartbeat age.
                "worker_alive": True,
                "updated_at": _utc_iso(),
            }
            tmp = self._status_path.with_suffix(".status.json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding=TEXT_ENCODING)
            tmp.replace(self._status_path)
        except Exception:
            return

    # ── batch processing ────────────────────────────────────────────────────

    def _get_embedder(self):
        if self._text_embedder is None:
            from agsuperbrain.memory.vector.embedder import TextEmbedder

            self._text_embedder = TextEmbedder()
        return self._text_embedder

    def _generate_reports(self) -> None:
        """Refresh `.agsuperbrain/graph.html` and `GRAPH_REPORT.md`."""
        output_dir = self.project_root / ".agsuperbrain"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        html_path = output_dir / "graph.html"
        report_path = output_dir / "GRAPH_REPORT.md"
        try:
            viz(self.gs, html_path, None, 3)
        except Exception as e:
            console.print(f"[yellow]Warning: failed to generate graph.html: {e}[/yellow]")
        try:
            md = generate_report(self.gs)
            report_path.write_text(md, encoding=TEXT_ENCODING)
        except Exception as e:
            console.print(f"[yellow]Warning: failed to generate GRAPH_REPORT.md: {e}[/yellow]")

    def _process_batch(self, changes: set[tuple[Change, str]]) -> None:
        """Apply one debounced batch of file events to the graph + vector store."""
        modified: set[Path] = set()
        deleted: set[Path] = set()
        for ch, raw_path in changes:
            p = _norm(Path(raw_path))
            # Filter: only files we'd consider source code, only existing files
            # for non-deleted events. The watchfiles filter already screens
            # most of this; this is belt-and-braces for race conditions.
            if p.suffix.lower() not in _CODE_SUFFIXES:
                continue
            if ch == Change.deleted:
                deleted.add(p)
            elif p.exists() and p.is_file():
                modified.add(p)

        if not modified and not deleted:
            self._current_batch = set()
            self._write_status(state="idle")
            return

        self._current_batch = modified | deleted
        self._last_flush_at = _utc_iso()
        self._last_error = None
        self._write_status(state="flushing")

        try:
            # Delete-sweep first so the graph reflects file removals before
            # we re-ingest the modified set.
            n_swept = self._pipeline.sync_deleted_files() if deleted else 0
            if n_swept:
                console.print(f"[dim]Removed {n_swept} graph entry(ies) for deleted files.[/dim]")

            if modified:
                files = sorted(modified)
                console.print(f"[cyan]Re-indexing {len(files)} file(s):[/cyan]")
                for p in files:
                    console.print(f"  [green]{p}[/green]")
                self._pipeline.run(files, verbose=True)

                # Incremental Qdrant re-embed for just the changed source paths.
                try:
                    from agsuperbrain.core.index_pipeline import VectorIndexPipeline

                    m = VectorIndexPipeline(
                        self.gs,
                        self.vs,
                        self._get_embedder(),
                    ).reindex_source_paths(files)
                    if m:
                        console.print(
                            f"[green]✓[/green] Qdrant incremental reindex: {m} node(s) — "
                            "[bold]search_code[/bold] in sync (not a full reindex)"
                        )
                except Exception as exc:
                    console.print(f"[yellow]Warning: Qdrant re-embed failed:[/yellow] {exc}")
                    console.print(
                        "[dim]Graph is up to date; run [cyan]agsuperbrain index-vectors[/cyan] to fix vectors.[/dim]"
                    )

                self._last_indexed = [str(p) for p in files]
                self._files_processed += len(files)

            self._generate_reports()
            self._batches_processed += 1
        except Exception as exc:
            self._last_error = f"batch failed: {exc}"
            self._write_status(state="error")
            console.print(f"[red]Batch failed:[/red] {exc}")
            return
        finally:
            self._current_batch = set()

        self._write_status(state="idle")

    # ── public API ──────────────────────────────────────────────────────────

    def run_once(self) -> int:
        """Single-pass scan: hash every code file, reindex what's changed.

        Used by `agsuperbrain watch --once`. Doesn't depend on watchfiles —
        it's a synchronous one-shot.
        """
        # Collect every code file under the watch paths.
        files: list[Path] = []
        for wp in self.watch_paths:
            if not wp.exists():
                continue
            if wp.is_file():
                if wp.suffix.lower() in _CODE_SUFFIXES:
                    files.append(_norm(wp))
                continue
            for fp in wp.rglob("*"):
                if not fp.is_file():
                    continue
                if any(part in (self.exclude_dirs | {".agsuperbrain", "output"}) for part in fp.parts):
                    continue
                if fp.suffix.lower() in _CODE_SUFFIXES:
                    files.append(_norm(fp))

        n_swept = self._pipeline.sync_deleted_files()
        if not files:
            if n_swept:
                console.print(f"[dim]Removed {n_swept} graph entry(ies) for missing files.[/dim]")
                self._generate_reports()
            console.print("[dim]No code files found.[/dim]")
            return 0

        # Treat them all as modified so the existing batch path runs.
        synthetic = {(Change.modified, str(p)) for p in files}
        self._process_batch(synthetic)
        return len(files)

    def start(
        self,
        debounce: float = 0.4,
        # `max_wait` is kept in the signature so callers from older versions
        # still work, but watchfiles uses pure trailing-edge debounce.
        max_wait: float | None = None,
        use_polling: bool = False,
        poll_interval: float = 2.0,
    ) -> None:
        """Run the watcher forever (or until `stop()` / Ctrl+C / signal).

        Args:
            debounce: seconds to wait after the last event before processing
                a batch. Default 0.4 keeps responsiveness on dev machines.
            max_wait: deprecated; watchfiles uses pure trailing-edge debounce
                and ignores this. Kept in the signature so callers don't break.
            use_polling: force watchfiles into polling mode for network shares
                where kernel file events don't work (NFS, SMB, some Docker
                volumes). Polling is more CPU-intensive but reliable.
            poll_interval: seconds between polls when `use_polling=True`.
        """
        valid = [p for p in self.watch_paths if p.exists()]
        if not valid:
            raise RuntimeError("No valid watch paths — paths must exist")

        debounce_ms = max(50, int(debounce * 1000))
        poll_delay_ms = max(100, int(poll_interval * 1000))
        backend = "polling" if use_polling else "native"
        console.print(
            f"[green]watchfiles watcher running[/green] "
            f"(backend={backend}, debounce={debounce_ms}ms) — [dim]Ctrl+C to stop[/dim]"
        )

        try:
            for changes in watch(
                *(str(p) for p in valid),
                step=50,
                debounce=debounce_ms,
                watch_filter=_CodeFilter(self.exclude_dirs),
                stop_event=self._stop_event,
                yield_on_timeout=True,  # gives us a tick to refresh heartbeat when idle
                rust_timeout=1000,  # 1s — heartbeat granularity
                force_polling=use_polling,
                poll_delay_ms=poll_delay_ms,
                recursive=True,
                ignore_permission_denied=True,
                raise_interrupt=False,
            ):
                # Heartbeat: prove we're alive every tick, even with no events.
                self._last_heartbeat_at = _utc_iso()
                if not changes:
                    # Idle tick (yield_on_timeout). Refresh status periodically
                    # so `watch-status` can compute a fresh heartbeat age.
                    self._write_status(state="idle")
                    continue
                self._current_batch = {_norm(Path(p)) for _, p in changes}
                self._write_status(state="pending")
                self._process_batch(changes)
        except KeyboardInterrupt:
            self._stop_event.set()
        except Exception as exc:
            self._last_error = f"watch loop failed: {exc}"
            self._write_status(state="error")
            raise
        finally:
            self._write_status(state="idle")

    def stop(self) -> None:
        """Signal the `watch()` generator to exit cleanly."""
        self._stop_event.set()
