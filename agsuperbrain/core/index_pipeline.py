"""Embed graph nodes (Kuzu) into Qdrant via `TextEmbedder` (deterministic, no LLM)."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from agsuperbrain.memory.graph.graph_store import GraphStore
from agsuperbrain.memory.vector.embedder import TextEmbedder
from agsuperbrain.memory.vector.vector_store import VectorPoint, VectorStore
from agsuperbrain.terminal import console


@dataclass
class _Row:
    node_id: str
    node_type: str
    text: str
    source_type: str
    source_path: str
    chunk_id: str
    body: str = ""
    docstring: str = ""


def _s(val: object) -> str:
    return str(val) if val is not None else ""


def _path_match_variants(fp: Path) -> set[str]:
    """Strings that may appear in the graph for the same file (rel vs resolved, etc.)."""
    out: set[str] = {str(fp)}
    try:
        out.add(str(fp.resolve()))
    except OSError:
        pass
    for s in list(out):
        out.add(os.path.normpath(s))
    return out


class VectorIndexPipeline:
    """
    Usage:
        pip = VectorIndexPipeline(graph_store, vector_store, embedder)
        total = pip.run()
    """

    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore,
        embedder: TextEmbedder,
        batch_size: int = 64,
    ) -> None:
        self.gs = graph_store
        self.vs = vector_store
        self.embedder = embedder
        self.batch_size = batch_size

    def _functions(self) -> list[_Row]:
        rows = []
        for r in self.gs.query(
            "MATCH (f:Function) RETURN f.id, f.qualified_name, f.source_type, f.source_path,        f.body, f.docstring"
        ):
            text = _s(r[1]).strip() or _s(r[0])  # fallback to node_id if name empty
            rows.append(
                _Row(
                    node_id=r[0],
                    node_type="Function",
                    text=text,
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id="",
                    body=_s(r[4]),
                    docstring=_s(r[5]),
                )
            )
        return rows

    def _sections(self) -> list[_Row]:
        rows = []
        for r in self.gs.query("MATCH (s:Section) RETURN s.id, s.title, s.source_type, s.source_path, s.chunk_id"):
            rows.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Section",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id=_s(r[4]),
                )
            )
        return rows

    def _concepts(self) -> list[_Row]:
        rows = []
        for r in self.gs.query("MATCH (c:Concept) RETURN c.id, c.text, c.source_type, c.source_path, c.chunk_id"):
            rows.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Concept",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id=_s(r[4]),
                )
            )
        return rows

    def _transcripts(self) -> list[_Row]:
        rows = []
        for r in self.gs.query("MATCH (t:Transcript) RETURN t.id, t.text, t.source_type, t.source_path, t.chunk_id"):
            rows.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Transcript",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id=_s(r[4]),
                )
            )
        return rows

    def _modules(self) -> list[_Row]:
        rows = []
        for r in self.gs.query("MATCH (m:Module) RETURN m.id, m.name, m.source_type, m.source_path"):
            rows.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Module",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id="",
                )
            )
        return rows

    def _upsert_rows(self, all_rows: list[_Row], *, show_header: bool = True) -> int:
        """Embed and upsert the given rows (shared by full run and targeted reindex)."""
        if not all_rows:
            return 0

        if show_header:
            console.print(
                f"\n[dim]Total:[/dim] {len(all_rows)} nodes | dim={self.embedder.dimension} | batch={self.batch_size}\n"
            )

        self.vs.ensure_collection(self.embedder.dimension)

        total = 0
        t0 = time.perf_counter()

        def _node_id_to_point_id(node_id: str) -> int:
            h = hashlib.sha256(node_id.encode()).hexdigest()[:16]
            return int(h, 16)

        with Progress(
            SpinnerColumn("line"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            task = prog.add_task("Embedding & upserting…", total=len(all_rows))

            for i in range(0, len(all_rows), self.batch_size):
                batch = all_rows[i : i + self.batch_size]
                texts = [r.text for r in batch]
                vectors = self.embedder.embed(texts)

                points = [
                    VectorPoint(
                        id=_node_id_to_point_id(row.node_id),
                        vector=vec,
                        node_id=row.node_id,
                        node_type=row.node_type,
                        text=row.text,
                        source_type=row.source_type,
                        source_path=row.source_path,
                        chunk_id=row.chunk_id,
                        body=row.body,
                        docstring=row.docstring,
                    )
                    for row, vec in zip(batch, vectors, strict=True)
                ]
                self.vs.upsert(points)
                total += len(points)
                prog.advance(task, len(batch))

        elapsed = time.perf_counter() - t0
        if show_header:
            console.rule("[bold green]Done")
        console.print(f"  Indexed [bold]{total}[/bold] vectors  ({elapsed:.1f}s)")
        return total

    def _rows_for_source_paths(self, path_list: list[str]) -> list[_Row]:
        """
        Load indexable rows only for the given `source_path` values (Kùzu `IN` — no
        full-table scan). Used for incremental reindex; full `run()` still scans all.
        """
        if not path_list:
            return []
        p = {"paths": path_list}
        out: list[_Row] = []

        for r in self.gs.query(
            "MATCH (m:Module) WHERE m.source_path IN $paths RETURN m.id, m.name, m.source_type, m.source_path",
            p,
        ):
            out.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Module",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id="",
                )
            )

        for r in self.gs.query(
            "MATCH (f:Function) WHERE f.source_path IN $paths "
            "RETURN f.id, f.qualified_name, f.source_type, f.source_path, f.body, f.docstring",
            p,
        ):
            text = _s(r[1]).strip() or _s(r[0])
            out.append(
                _Row(
                    node_id=r[0],
                    node_type="Function",
                    text=text,
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id="",
                    body=_s(r[4]),
                    docstring=_s(r[5]),
                )
            )

        for r in self.gs.query(
            "MATCH (s:Section) WHERE s.source_path IN $paths "
            "RETURN s.id, s.title, s.source_type, s.source_path, s.chunk_id",
            p,
        ):
            out.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Section",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id=_s(r[4]),
                )
            )

        for r in self.gs.query(
            "MATCH (c:Concept) WHERE c.source_path IN $paths "
            "RETURN c.id, c.text, c.source_type, c.source_path, c.chunk_id",
            p,
        ):
            out.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Concept",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id=_s(r[4]),
                )
            )

        for r in self.gs.query(
            "MATCH (t:Transcript) WHERE t.source_path IN $paths "
            "RETURN t.id, t.text, t.source_type, t.source_path, t.chunk_id",
            p,
        ):
            out.append(
                _Row(
                    node_id=_s(r[0]),
                    node_type="Transcript",
                    text=_s(r[1]) or _s(r[0]),
                    source_type=_s(r[2]),
                    source_path=_s(r[3]),
                    chunk_id=_s(r[4]),
                )
            )
        return out

    def reindex_source_paths(self, source_files: list[Path]) -> int:
        """
        **Incremental** vector pass (not a full reindex): drop Qdrant points for
        the given file paths, then re-embed only the graph nodes whose
        `source_path` is in that set. Work scales with the number of changed
        files / matching nodes, not the size of the whole repo. For a full
        rebuild, use `agsuperbrain index-vectors` without a path filter.
        """
        if not source_files:
            return 0

        path_set: set[str] = set()
        for fp in source_files:
            path_set |= _path_match_variants(fp)

        path_list = list(path_set)
        if not path_list:
            return 0

        for p in path_list:
            self.vs.delete_by_source_path(p)

        all_rows = self._rows_for_source_paths(path_list)
        if not all_rows:
            console.print("[dim]Vector reindex: no graph nodes for changed paths (ok if files empty).[/dim]")
            return 0

        console.print(
            f"[cyan]Vector reindex (incremental):[/cyan] {len(all_rows)} node(s) for "
            f"{len(source_files)} file(s) — [bold]search_code[/bold] in sync; "
            f"[dim]full rebuild = `agsuperbrain index-vectors`[/dim]"
        )
        return self._upsert_rows(all_rows, show_header=False)

    def run(self, incremental: bool = False) -> int:
        console.rule("[bold cyan]Super-Brain Phase 5: Vector Indexing")

        existing_node_ids: set[str] = set()
        if incremental:
            try:
                existing = self.vs.search(
                    query_vector=[0.0] * self.embedder.dimension,
                    limit=100000,
                )
                existing_node_ids = {r.node_id for r in existing}
                console.print(f"[dim]Incremental mode: {len(existing_node_ids)} existing vectors[/dim]")
            except Exception:
                pass

        all_rows: list[_Row] = []
        for label, collector in [
            ("Module", self._modules),
            ("Function", self._functions),
            ("Section", self._sections),
            ("Concept", self._concepts),
            ("Transcript", self._transcripts),
        ]:
            chunk = collector()
            console.print(f"  {label:<12} [dim]{len(chunk)} nodes[/dim]")
            all_rows.extend(chunk)

        if incremental and existing_node_ids:
            all_rows = [r for r in all_rows if r.node_id not in existing_node_ids]
            console.print(f"[dim]Skipping {len(existing_node_ids)} already indexed nodes[/dim]")

        if not all_rows:
            console.print("[yellow]No nodes found. Run ingest commands first.[/yellow]")
            return 0

        total = self._upsert_rows(all_rows, show_header=True)
        return total
