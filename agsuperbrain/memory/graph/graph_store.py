"""
graph_store.py — KùzuDB graph store (Phase 1 + Phase 3 + Phase 4).

FIX: KùzuDB CREATE node properties must ALL be $params — no inline
     string literals like source_type:'audio' inside CREATE {}.
     Every constant is now passed as an explicit parameter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import kuzu

from agsuperbrain.extraction.models import ExtractionResult
from agsuperbrain.memory.graph.schema import ALL_DDL

# (Kùzu node table, FTS index name, indexed columns) — also used by search_fts
_FTS_INDEX_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Function", "function_fts", ("name", "qualified_name", "body", "docstring")),
    ("Concept", "concept_fts", ("text",)),
)


def _nid(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class GraphStore:
    def __init__(self, db_path: Path) -> None:
        if db_path.suffix == "":
            db_path = db_path / "superbrain.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(db_path))
        self._conn = kuzu.Connection(self._db)

    def close(self) -> None:
        """Release the KùzuDB connection and database handles.

        Safe to call multiple times. Allows the OS to release the file lock
        so the same DB directory can be reopened in another process.
        """
        conn = getattr(self, "_conn", None)
        if conn is not None and hasattr(conn, "close"):
            try:
                conn.close()
            except Exception:
                pass
            self._conn = None

        db = getattr(self, "_db", None)
        if db is not None and hasattr(db, "close"):
            try:
                db.close()
            except Exception:
                pass
            self._db = None

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def init_schema(self) -> None:
        for ddl in ALL_DDL:
            self._conn.execute(ddl)
        self._ensure_fts_indices()

    def _ensure_fts_indices(self) -> None:
        """Best-effort full-text indexes (Kùzu has no generic B-tree on arbitrary STRING keys)."""
        for table, index_name, columns in _FTS_INDEX_SPECS:
            cols = "[" + ", ".join(f"'{c}'" for c in columns) + "]"
            q = f"CALL CREATE_FTS_INDEX('{table}', '{index_name}', {cols})"
            try:
                self._conn.execute(q)
            except Exception:
                # FTS is optional: missing extension, version quirks, or duplicate index.
                continue

    def search_fts(
        self,
        query: str,
        *,
        node_type: str | None = None,
        per_table_limit: int = 15,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Run Kùzu `QUERY_FTS_INDEX` over built FTS tables (Function, Concept when applicable).

        Returns rows with: node_id, node_type, text, source_path, source_type, score.
        On failure (no extension, no index) returns an empty list.
        """
        q = (query or "").strip()
        if not q or per_table_limit < 1:
            return []

        specs: list[tuple[str, str, tuple[str, ...]]] = []
        for table, iname, cols in _FTS_INDEX_SPECS:
            if node_type in (None, table):
                specs.append((table, iname, cols))
        if not specs:
            return []

        out: list[dict[str, Any]] = []
        limit = int(per_table_limit)
        for table, iname, _ in specs:
            cypher = f"CALL QUERY_FTS_INDEX('{table}', '{iname}', $q) RETURN node, score LIMIT {limit}"
            try:
                res = self._conn.execute(cypher, {"q": q})
            except Exception:
                try:
                    esc = q.replace("\\", "\\\\").replace("'", "\\'")
                    alt = f"CALL QUERY_FTS_INDEX('{table}', '{iname}', '{esc}') RETURN node, score LIMIT {limit}"
                    res = self._conn.execute(alt)
                except Exception:
                    continue
            if res is None:
                continue
            while res.has_next():
                row = res.get_next()
                if not row or len(row) < 2:
                    continue
                node, score = row[0], row[1]
                if not isinstance(node, dict) or not node.get("id"):
                    continue
                st = str(node.get("source_type") or "")
                if source_type is not None and st != str(source_type):
                    continue
                if table == "Function":
                    text = str(node.get("qualified_name") or node.get("name") or node.get("body") or "")
                else:
                    text = str(node.get("text") or node.get("title") or node.get("name") or "")

                out.append(
                    {
                        "node_id": str(node["id"]),
                        "node_type": table,
                        "text": text,
                        "source_type": st,
                        "source_path": str(node.get("source_path") or ""),
                        "chunk_id": str(node.get("chunk_id") or ""),
                        "score": float(score) if score is not None else 0.0,
                    }
                )
        return out

    def _run(self, q: str, p: dict | None = None):
        try:
            return self._conn.execute(q, p) if p else self._conn.execute(q)
        except RuntimeError as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                return None
            raise

    # ── helpers ───────────────────────────────────────────────────────────

    def _create_node(self, label: str, props: dict) -> None:
        """
        Upsert a node by primary key `id`.

        MERGE matches by id; SET refreshes every other property, so
        re-ingestion actually updates changed fields (body, end_line, etc.)
        instead of silently no-oping on duplicate-key errors.
        """
        if "id" not in props:
            raise ValueError(f"_create_node({label}) requires 'id' in props")
        set_keys = [k for k in props if k != "id"]
        query = f"MERGE (n:{label} {{id:$id}})"
        if set_keys:
            query += " SET " + ", ".join(f"n.{k}=${k}" for k in set_keys)
        self._run(query, props)

    def _merge_edge(
        self,
        from_label: str,
        from_id: str,
        to_label: str,
        to_id: str,
        rel: str,
        rel_props: dict,
    ) -> None:
        """Generic MERGE for any edge type."""
        pairs = ", ".join(f"{k}:${k}" for k in rel_props)
        self._run(
            f"MATCH (a:{from_label} {{id:$from_id}}), "
            f"      (b:{to_label}   {{id:$to_id}}) "
            f"MERGE (a)-[:{rel} {{{pairs}}}]->(b)",
            {"from_id": from_id, "to_id": to_id, **rel_props},
        )

    # ── Phase 1: Code ─────────────────────────────────────────────────────

    def _delete_code_nodes_for_source_path(self, source_path: str) -> None:
        """Remove Module + Function nodes tied to a code file's `source_path`.

        Function primary keys embed the current qualified name (`stem__qualname`).
        A rename therefore produces a new `id` while the old `Function` row stays
        unless we delete by path before re-upsert. Safe to run before every
        `upsert_extraction` (same as replace-from-disk for that file).
        """
        for label in ("Module", "Function"):
            self._run(
                f"MATCH (n:{label}) WHERE n.source_path = $sp DETACH DELETE n",
                {"sp": source_path},
            )

    def upsert_extraction(self, ex: ExtractionResult) -> None:
        self._delete_code_nodes_for_source_path(ex.source_path)
        sp = Path(ex.source_path)
        mid = _nid(sp.stem)

        self._create_node(
            "Module",
            {
                "id": mid,
                "name": sp.stem,
                "source_path": ex.source_path,
                "source_type": "code",
                "language": ex.language,
            },
        )

        # Synthetic <module>-scope Function so calls made at module level
        # (rule_engine emits caller_id = f"{mid}____module__") have a real
        # node to hang CALLS edges off. Keep id in sync with rule_engine.
        module_scope_id = f"{mid}____module__"
        self._create_node(
            "Function",
            {
                "id": module_scope_id,
                "name": "<module>",
                "qualified_name": f"{sp.stem}.<module>",
                "source_path": ex.source_path,
                "source_type": "code",
                "language": ex.language,
                "start_line": 0,
                "end_line": 0,
                "is_method": False,
                "class_name": "",
                "body": "",
                "docstring": "",
            },
        )
        self._merge_edge(
            "Function",
            module_scope_id,
            "Module",
            mid,
            "DEFINED_IN",
            {"source_path": ex.source_path},
        )

        known: set[str] = {module_scope_id}
        for f in ex.functions:
            self._create_node(
                "Function",
                {
                    "id": f.node_id,
                    "name": f.name,
                    "qualified_name": f.qualified_name,
                    "source_path": f.source_path,
                    "source_type": "code",
                    "language": f.language,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "is_method": f.is_method,
                    "class_name": f.class_name or "",
                    "body": f.body,  # ← ADD
                    "docstring": f.docstring,  # ← ADD
                },
            )
            self._merge_edge(
                "Function",
                f.node_id,
                "Module",
                mid,
                "DEFINED_IN",
                {"source_path": f.source_path},
            )
            known.add(f.node_id)

        for c in ex.calls:
            if c.callee_id not in known:
                self._create_node(
                    "Function",
                    {
                        "id": c.callee_id,
                        "name": c.callee_name,
                        "qualified_name": c.callee_name,
                        "source_path": "external",
                        "source_type": "external",
                        "language": "unknown",
                        "start_line": 0,
                        "end_line": 0,
                        "is_method": False,
                        "class_name": "",
                        "body": "",
                        "docstring": "",
                    },
                )
            self._merge_edge(
                "Function",
                c.caller_id,
                "Function",
                c.callee_id,
                "CALLS",
                {
                    "call_line": c.call_line,
                    "source_path": c.source_path,
                    "confidence": c.confidence,
                    "confidence_type": c.confidence_type,
                },
            )

    # ── Phase 3: Documents ────────────────────────────────────────────────

    def upsert_doc(self, ex) -> None:
        self._create_node(
            "Document",
            {
                "id": ex.doc_node_id,
                "title": ex.doc_title,
                "source_path": ex.source_path,
                "source_type": ex.source_type,
            },
        )

        for s in ex.sections:
            self._create_node(
                "Section",
                {
                    "id": s.node_id,
                    "title": s.title,
                    "level": s.level,
                    "source_path": s.source_path,
                    "source_type": s.source_type,
                    "chunk_id": s.chunk_id,
                },
            )
            if s.parent_id == ex.doc_node_id:
                self._merge_edge(
                    "Document",
                    s.parent_id,
                    "Section",
                    s.node_id,
                    "CONTAINS",
                    {
                        "relation": "has_section",
                        "source_path": s.source_path,
                    },
                )
            else:
                self._merge_edge(
                    "Section",
                    s.parent_id,
                    "Section",
                    s.node_id,
                    "CONTAINS",
                    {
                        "relation": "has_subsection",
                        "source_path": s.source_path,
                    },
                )

        for c in ex.concepts:
            self._create_node(
                "Concept",
                {
                    "id": c.node_id,
                    "text": c.text,
                    "source_path": c.source_path,
                    "source_type": c.source_type,
                    "chunk_id": c.chunk_id,
                },
            )
            self._merge_edge(
                "Section",
                c.parent_id,
                "Concept",
                c.node_id,
                "CONTAINS",
                {
                    "relation": "mentions",
                    "source_path": c.source_path,
                },
            )

    # ── Phase 4: Audio ────────────────────────────────────────────────────

    def upsert_audio(self, ex) -> None:
        src = ex.source

        self._create_node(
            "AudioSource",
            {
                "id": src.node_id,
                "title": src.title,
                "source_url": src.source_url,
                "source_type": src.source_type,
                "wav_path": src.wav_path,
                "duration_s": src.duration_s,
            },
        )

        for seg in ex.segments:
            self._create_node(
                "Transcript",
                {
                    "id": seg.node_id,
                    "text": seg.text,
                    "start_sec": seg.start_sec,
                    "end_sec": seg.end_sec,
                    "seq_index": seg.seq_index,
                    "chunk_id": seg.chunk_id,
                    "source_path": seg.source_path,
                    "source_type": seg.source_type,
                },
            )
            self._merge_edge(
                "Transcript",
                seg.node_id,
                "AudioSource",
                src.node_id,
                "SOURCE",
                {"source_path": seg.source_path},
            )

        for i in range(len(ex.segments) - 1):
            curr = ex.segments[i]
            nxt = ex.segments[i + 1]
            self._merge_edge(
                "Transcript",
                curr.node_id,
                "Transcript",
                nxt.node_id,
                "FOLLOWS",
                {"source_path": curr.source_path},
            )

    # ── Cross-modal edges (P2) ───────────────────────────────────────────────

    def link_documented_by(self, function_id: str, section_id: str, source_path: str, confidence: float = 1.0) -> None:
        self._merge_edge(
            "Function",
            function_id,
            "Section",
            section_id,
            "DOCUMENTED_BY",
            {"source_path": source_path, "confidence": confidence},
        )

    def link_mentions(
        self, from_id: str, from_label: str, to_id: str, to_label: str, source_path: str, confidence: float = 1.0
    ) -> None:
        self._merge_edge(
            from_label,
            from_id,
            to_label,
            to_id,
            "MENTIONS",
            {"source_path": source_path, "confidence": confidence},
        )

    # ── Data-flow edges (P2) ──────────────────────────────────────────────

    def link_reads(self, reader_id: str, target_id: str, source_path: str, var_name: str = "") -> None:
        self._merge_edge(
            "Function",
            reader_id,
            "Function",
            target_id,
            "READS",
            {"source_path": source_path, "var_name": var_name},
        )

    def link_writes(self, writer_id: str, target_id: str, source_path: str, var_name: str = "") -> None:
        self._merge_edge(
            "Function",
            writer_id,
            "Function",
            target_id,
            "WRITES",
            {"source_path": source_path, "var_name": var_name},
        )

    def link_returns_type(self, function_id: str, type_name: str, source_path: str) -> None:
        self._merge_edge(
            "Function",
            function_id,
            "Function",
            function_id,
            "RETURNS_TYPE",
            {"source_path": source_path, "type_name": type_name},
        )

    def link_param_type(self, function_id: str, param_name: str, type_name: str, source_path: str) -> None:
        self._merge_edge(
            "Function",
            function_id,
            "Function",
            function_id,
            "PARAM_TYPE",
            {
                "source_path": source_path,
                "param_name": param_name,
                "type_name": type_name,
            },
        )

    # ── Query API ─────────────────────────────────────────────────────────

    def query(self, cypher: str, params: dict | None = None) -> list[list]:
        res = self._run(cypher, params)
        if res is None:
            return []
        rows = []
        while res.has_next():
            rows.append(res.get_next())
        return rows

    def get_all_functions(self) -> list[list]:
        return self.query(
            "MATCH (f:Function) "
            "RETURN f.id, f.name, f.qualified_name, "
            "f.source_path, f.language, f.start_line, f.end_line"
        )

    def get_all_calls(self) -> list[list]:
        return self.query("MATCH (cr:Function)-[c:CALLS]->(ce:Function) RETURN cr.id, ce.id, c.call_line, c.confidence")

    # ── Full-graph export (for visualizer) ───────────────────────────────

    _NODE_LABELS: tuple[str, ...] = (
        "Module",
        "Function",
        "Document",
        "Section",
        "Concept",
        "AudioSource",
        "Transcript",
    )
    _REL_TABLES: tuple[str, ...] = (
        "CALLS",
        "DEFINED_IN",
        "CONTAINS",
        "SOURCE",
        "FOLLOWS",
        "DOCUMENTED_BY",
        "MENTIONS",
        "READS",
        "WRITES",
        "RETURNS_TYPE",
        "PARAM_TYPE",
    )

    def export_graph_json(self) -> dict:
        """
        Dump every node and every edge across all phases into a JSON-shaped
        dict the Cytoscape visualizer can render directly.

        Node dict carries whatever fields the label actually stores; a
        'label' field is synthesised from qualified_name/name/title/text
        so the UI always has something to display.

        Edge dict shape: {source, target, relation, ...rel-props}.
        """
        nodes: list[dict] = []
        seen_node_ids: set[str] = set()

        for label in self._NODE_LABELS:
            res = self._run(f"MATCH (n:{label}) RETURN n")
            if res is None:
                continue
            while res.has_next():
                (raw,) = res.get_next()
                if not isinstance(raw, dict):
                    continue
                nid = raw.get("id")
                if not nid or nid in seen_node_ids:
                    continue
                seen_node_ids.add(nid)
                display = (
                    raw.get("qualified_name")
                    or raw.get("name")
                    or raw.get("title")
                    or (raw.get("text") or "")[:60]
                    or nid
                )
                node = {k: v for k, v in raw.items() if not str(k).startswith("_")}
                node["node_label"] = label
                node["label"] = display
                node.setdefault(
                    "source_type",
                    "code"
                    if label in ("Module", "Function")
                    else "document"
                    if label in ("Document", "Section", "Concept")
                    else "audio",
                )
                nodes.append(node)

        edges: list[dict] = []
        for rel in self._REL_TABLES:
            res = self._run(f"MATCH (a)-[r:{rel}]->(b) RETURN a.id, b.id, r")
            if res is None:
                continue
            while res.has_next():
                src_id, dst_id, rprops = res.get_next()
                edge = {
                    "source": src_id,
                    "target": dst_id,
                    "relation": rel,
                }
                if isinstance(rprops, dict):
                    for k, v in rprops.items():
                        if str(k).startswith("_"):
                            continue
                        edge.setdefault(k, v)
                edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    # ── Deletion / incremental sync ──────────────────────────────────────

    def delete_source_file(self, source_path: str) -> None:
        """
        Remove every node (and its attached edges) that originated from
        `source_path`. Safe to call when the path no longer exists on
        disk — used by CodeGraphPipeline.sync_deleted_files().
        """
        for label in self._NODE_LABELS:
            self._run(
                f"MATCH (n:{label}) WHERE n.source_path = $sp DETACH DELETE n",
                {"sp": source_path},
            )

    def get_subgraph(
        self,
        root_id: str,
        max_depth: int = 2,
        node_type: str = "Function",
    ) -> tuple[list[dict], list[dict]]:
        res = self._run(
            f"MATCH p=(r:{node_type} {{id:$rid}})-[*1..{max_depth}]->(n) RETURN nodes(p), rels(p)",
            {"rid": root_id},
        )
        if res is None:
            return [], []
        nodes_map: dict[str, dict] = {}
        edges: list[dict] = []
        while res.has_next():
            node_list, rel_list = res.get_next()
            for node in node_list:
                nid = node.get("id") or str(node)
                if nid not in nodes_map:
                    nodes_map[nid] = {
                        "id": nid,
                        "label": (node.get("name") or node.get("title") or node.get("text", nid)[:40]),
                        "source_path": node.get("source_path", ""),
                        "source_type": node.get("source_type", "code"),
                    }
            for rel in rel_list:
                src = rel.get("_src", {})
                dst = rel.get("_dst", {})
                edges.append(
                    {
                        "source": src.get("id", "") if isinstance(src, dict) else str(src),
                        "target": dst.get("id", "") if isinstance(dst, dict) else str(dst),
                        "relation": rel.get("relation", "EDGE"),
                    }
                )
        return list(nodes_map.values()), edges
