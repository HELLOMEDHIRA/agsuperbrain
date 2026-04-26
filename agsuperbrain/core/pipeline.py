"""Code graph: pass A (parse/index), pass B (resolve calls, upsert). Linking to docs/audio is separate."""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from agsuperbrain.extraction.import_resolver import extract_imports
from agsuperbrain.extraction.project_index import ProjectIndex
from agsuperbrain.extraction.rule_engine import RuleEngine
from agsuperbrain.memory.graph.graph_store import GraphStore
from agsuperbrain.preprocessing.code_parser import CodeParser, detect_language
from agsuperbrain.terminal import TEXT_ENCODING, console

DEFAULT_EXCLUDE_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "env",
        ".env",
        "ENV",
        "node_modules",
        ".npm",
        ".yarn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        "*.swp",
        "*.swo",
        "*~",
        ".tox",
        ".nox",
        ".cache",
    }
)

DEFAULT_EXCLUDE_PATTERNS = frozenset(
    {
        "*.pyc",
        "*.pyo",
        "*.so",
        "*.dylib",
        "*.dll",
        "*.class",
        "*.o",
        "*.obj",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "*.min.js",
        "*.bundle.js",
        "type_script_temp_*",
    }
)

SUPERBRAINIGNORE = ".agsuperbrainignore"


def _load_superbrainignore(root: Path) -> frozenset[str]:
    """Load .agsuperbrainignore file from project root."""
    ignore_file = root / SUPERBRAINIGNORE
    if ignore_file.exists():
        entries = set()
        for line in ignore_file.read_text(encoding=TEXT_ENCODING).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entries.add(line)
        return frozenset(entries)
    return frozenset()


def _load_gitignore(root: Path) -> frozenset[str]:
    """Load .gitignore file from project root."""
    gitignore = root / ".gitignore"
    if gitignore.exists():
        entries = set()
        for line in gitignore.read_text(encoding=TEXT_ENCODING).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entries.add(line)
        return frozenset(entries)
    return frozenset()


@dataclass
class PipelineResult:
    files_processed: int = 0
    files_failed: int = 0
    total_functions: int = 0
    total_calls: int = 0
    elapsed_seconds: float = 0.0
    errors: list[tuple[str, str]] = field(default_factory=list)


class CodeGraphPipeline:
    def __init__(self, graph_store: GraphStore, vector_store=None) -> None:
        self._parser = CodeParser()
        self._extractor = RuleEngine()
        self._store = graph_store
        self._vector_store = vector_store

    def _collect(self, paths: list[Path], exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE_DIRS) -> list[Path]:
        gitignore_entries = frozenset()
        superbrainignore_entries = frozenset()
        for p in paths:
            if p.is_dir():
                gitignore_entries = _load_gitignore(p)
                superbrainignore_entries = _load_superbrainignore(p)
                break

        all_excludes = exclude_dirs.union(gitignore_entries).union(superbrainignore_entries)

        files: list[Path] = []
        for p in paths:
            if p.is_dir():
                for ext in (".py", ".js", ".ts", ".mjs"):
                    candidates = p.rglob(f"*{ext}")
                    for fp in candidates:
                        if any(part in all_excludes for part in fp.parts):
                            continue
                        if fp.name in all_excludes:
                            continue
                        files.append(fp)
            elif p.is_file() and detect_language(p):
                files.append(p)
        return sorted(set(files))

    def run(
        self, paths: list[Path], verbose: bool = False, exclude_dirs: frozenset[str] = DEFAULT_EXCLUDE_DIRS
    ) -> PipelineResult:
        files = self._collect(paths, exclude_dirs)
        summary = PipelineResult()
        t0 = time.perf_counter()

        console.rule("[bold cyan]Super-Brain · Phase 2: Code Graph")
        console.print(f"[dim]{len(files)} file(s) found.[/dim]\n")

        # ── PASS A: collect all FunctionDefs → build ProjectIndex ──────
        console.print("[bold]Pass A[/bold] — Indexing all functions…")
        all_parse_results = {}
        all_defs = []

        max_workers = min(os.cpu_count() or 4, 8)

        def _parse_file(fp):
            try:
                pr = self._parser.parse(fp)
                ex = self._extractor.extract(pr)
                return str(fp), pr, ex
            except Exception as exc:
                return str(fp), None, exc

        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            ta = prog.add_task("Parsing…", total=len(files))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_parse_file, fp): fp for fp in files}
                for future in as_completed(futures):
                    fp = futures[future]
                    prog.update(ta, description=f"[dim]{fp.name}[/dim]")
                    try:
                        path, pr, result = future.result()
                        if isinstance(result, Exception):
                            raise result
                        all_parse_results[path] = pr
                        all_defs.extend(result.functions)
                        for fdef in result.functions:
                            fdef.source_path = path
                    except Exception as exc:
                        summary.files_failed += 1
                        summary.errors.append((str(fp), str(exc)))
                        console.print(f"  ✗ [red]{fp.name}[/red] — {exc}")
                    prog.advance(ta)

        project_index = ProjectIndex.build(all_defs)
        console.print(
            f"  [green]✓[/green] Index built — "
            f"[bold]{len(all_defs)}[/bold] functions across "
            f"[bold]{len(all_parse_results)}[/bold] files\n"
        )

        # ── PASS B: resolve calls with cross-file index ─────────────────
        console.print("[bold]Pass B[/bold] — Resolving calls and writing to graph…")

        with Progress(
            SpinnerColumn("line"),
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            tb = prog.add_task("Extracting…", total=len(files))
            for fp in files:
                prog.update(tb, description=f"[cyan]{fp.name}[/cyan]")
                try:
                    pr = all_parse_results.get(str(fp))
                    if pr is None:
                        prog.advance(tb)
                        continue

                    import_map = extract_imports(pr)
                    ex = self._extractor.extract(
                        pr,
                        project_index=project_index,
                        import_map=import_map,
                    )
                    self._store.upsert_extraction(ex)

                    summary.files_processed += 1
                    summary.total_functions += len(ex.functions)
                    summary.total_calls += len(ex.calls)

                    if verbose:
                        console.print(f"  ✓ [green]{fp.name}[/green] — {len(ex.functions)} fns, {len(ex.calls)} calls")
                except Exception as exc:
                    summary.files_failed += 1
                    summary.errors.append((str(fp), str(exc)))
                    console.print(f"  ✗ [red]{fp.name}[/red] — {exc}")
                prog.advance(tb)

        summary.elapsed_seconds = time.perf_counter() - t0
        console.rule("[bold green]Phase 2 Complete")
        console.print(f"  Functions : {summary.total_functions}")
        console.print(f"  Calls     : {summary.total_calls}")
        console.print(f"  Elapsed   : {summary.elapsed_seconds:.2f}s")
        if summary.errors:
            console.print(f"  [red]Errors    : {summary.files_failed}[/red]")
        return summary

    def sync_deleted_files(self) -> int:
        """
        Compare what's in the graph against what exists on disk.
        Delete graph entries for any source file that no longer exists.
        Returns the number of files swept.
        """
        rows = self._store.query("MATCH (m:Module) RETURN m.source_path")
        removed = 0
        for row in rows:
            stored_path = Path(row[0])
            if not stored_path.exists():
                console.print(f"[yellow]Removing deleted file:[/yellow] {stored_path}")
                self._store.delete_source_file(str(stored_path))
                if self._vector_store is not None:
                    self._vector_store.delete_by_source_path(str(stored_path))
                removed += 1
        return removed


def _extract_keywords(text: str) -> set[str]:
    """Extract potential keywords from text for linking."""
    words = re.findall(r"\b[a-z][a-z0-9_]{2,20}\b", text.lower())
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "have",
        "has",
        "was",
        "were",
        "been",
        "being",
        "are",
        "but",
        "not",
        "all",
        "can",
        "had",
        "her",
        "she",
        "him",
        "his",
        "its",
        "one",
        "two",
        "our",
        "out",
        "any",
        "new",
        "use",
        "using",
        "used",
        "def",
        "class",
        "function",
        "return",
        "import",
        "export",
        "const",
        "let",
        "var",
        "if",
        "else",
        "while",
        "try",
        "except",
        "catch",
        "raise",
        "pass",
        "break",
        "continue",
    }
    return {w for w in words if w not in stopwords}


def link_documented_by(graph_store: GraphStore) -> int:
    """
    Link Sections to Functions via keyword matching.

    If a function's name/docstring appears in a section's title/text,
    create DOCUMENTED_BY edge.
    """
    linked = 0

    rows = graph_store.query("MATCH (s:Section) RETURN s.id, s.title, s.chunk_id")
    sections = {(r[0], r[1], r[2]) for r in rows if r[0]}

    fn_rows = graph_store.query("MATCH (f:Function) RETURN f.id, f.name, f.qualified_name, f.docstring")
    functions = {(r[0], r[1], r[2], r[3] or "") for r in fn_rows if r[0]}

    for sec_id, sec_title, _sec_chunk in sections:
        sec_keywords = _extract_keywords(sec_title)

        for fn_id, fn_name, fn_qual, fn_doc in functions:
            fn_keywords = _extract_keywords(fn_name) | _extract_keywords(fn_qual)
            if fn_doc:
                fn_keywords |= _extract_keywords(fn_doc)

            overlap = sec_keywords & fn_keywords
            if len(overlap) >= 2:
                graph_store.link_documented_by(fn_id, sec_id, "keyword_match", confidence=0.7)
                linked += 1

    return linked


def link_mentions(graph_store: GraphStore) -> int:
    """
    Link Transcripts to Functions/Concepts via keyword matching.

    If a function/concept name appears in transcript text,
    create MENTIONS edge.
    """
    linked = 0

    rows = graph_store.query("MATCH (t:Transcript) RETURN t.id, t.text")
    transcripts = [(r[0], r[1]) for r in rows if r[0] and r[1]]

    fn_rows = graph_store.query("MATCH (f:Function) RETURN f.id, f.name, f.qualified_name")
    functions = {(r[0], r[1], r[2]) for r in fn_rows if r[0]}

    concept_rows = graph_store.query("MATCH (c:Concept) RETURN c.id, c.text")
    concepts = {(r[0], r[1]) for r in concept_rows if r[0] and r[1]}

    for trans_id, trans_text in transcripts:
        trans_keywords = _extract_keywords(trans_text)

        for fn_id, fn_name, fn_qual in functions:
            fn_keywords = _extract_keywords(fn_name) | _extract_keywords(fn_qual)
            if trans_keywords & fn_keywords:
                graph_store.link_mentions(
                    trans_id,
                    "Transcript",
                    fn_id,
                    "Function",
                    "keyword_match",
                    confidence=0.6,
                )
                linked += 1

        for conc_id, conc_text in concepts:
            conc_keywords = _extract_keywords(conc_text)
            if trans_keywords & conc_keywords:
                graph_store.link_mentions(
                    trans_id,
                    "Transcript",
                    conc_id,
                    "Concept",
                    "keyword_match",
                    confidence=0.6,
                )
                linked += 1

    return linked
