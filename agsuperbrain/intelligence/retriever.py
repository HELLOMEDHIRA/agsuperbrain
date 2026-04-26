"""
retriever.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agsuperbrain.memory.graph.graph_store import GraphStore
from agsuperbrain.memory.vector.embedder import TextEmbedder
from agsuperbrain.memory.vector.vector_store import VectorStore

# ── Module-level constants (not rebuilt per call) ─────────────────
_EXTERNAL_STUB_NAMES: frozenset[str] = frozenset(
    {
        "load",
        "print",
        "open",
        "str",
        "int",
        "list",
        "dict",
        "len",
        "range",
        "type",
        "append",
        "get",
        "json",
        "os",
        "any",
        "all",
        "next",
        "iter",
        "read",
        "write",
        "close",
        "format",
        "split",
        "isinstance",
        "hasattr",
        "getattr",
    }
)

_GRAPH_QUERIES: dict[str, str] = {
    "Function": (
        "MATCH (f:Function {{id:$id}})-[:CALLS*1..{d}]-(n:Function) "
        "RETURN n.id, n.name AS label, n.qualified_name AS text, "
        "       n.source_path, n.source_type, 'Function' AS node_type"
    ),
    "Transcript": (
        "MATCH (t:Transcript {{id:$id}})-[:FOLLOWS*1..{d}]-(n:Transcript) "
        "RETURN n.id, n.id AS label, n.text AS text, "
        "       n.source_path, n.source_type, 'Transcript' AS node_type"
    ),
    "Section": (
        "MATCH (s:Section {{id:$id}})-[:CONTAINS*1..{d}]-(n:Section) "
        "RETURN n.id, n.title AS label, n.title AS text, "
        "       n.source_path, n.source_type, 'Section' AS node_type"
    ),
    "Concept": (
        "MATCH (c:Concept {{id:$id}})<-[:CONTAINS]-(s:Section) "
        "RETURN s.id, s.title AS label, s.title AS text, "
        "       s.source_path, s.source_type, 'Section' AS node_type"
    ),
}


@dataclass
class HybridResult:
    node_id: str
    node_type: str
    text: str
    source_type: str
    source_path: str
    chunk_id: str
    vector_score: float
    graph_hops: int
    final_score: float
    neighbours: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # ← FIX 5


class HybridRetriever:
    def __init__(
        self,
        graph_store: GraphStore,
        vector_store: VectorStore,
        embedder: TextEmbedder,
        graph_depth: int = 2,
        graph_decay: float = 0.7,
    ) -> None:
        self.gs = graph_store
        self.vs = vector_store
        self.embedder = embedder
        self.graph_depth = graph_depth
        self.graph_decay = graph_decay

    def _vector_search(self, query, top_k, node_type, source_type):
        vec = self.embedder.embed([query])[0]
        return self.vs.search(vec, limit=top_k, node_type=node_type, source_type=source_type)

    def _apply_fts(
        self,
        query_text: str,
        seen: dict[str, HybridResult],
        top_k: int,
        node_type: str | None,
        source_type: str | None,
    ) -> None:
        """Merge Kùzu FTS keyword matches with vector hit scores (RAG-style hybrid)."""
        ntab = 2 if node_type is None else 1
        per_table = max(5, min(50, max(top_k, top_k * 2 // max(1, ntab))))
        try:
            fts = self.gs.search_fts(
                query_text,
                node_type=node_type,
                per_table_limit=per_table,
                source_type=source_type,
            )
        except Exception:
            return
        if not fts:
            return
        max_s = max((float(h["score"]) for h in fts if h.get("score") is not None), default=0.0)
        if max_s <= 0:
            max_s = 1.0
        for h in fts:
            nid = str(h.get("node_id") or "")
            if not nid:
                continue
            norm = float(h.get("score") or 0.0) / max_s
            ntype = str(h.get("node_type") or "")
            text = str(h.get("text") or "")
            st = str(h.get("source_type") or "")
            sp = str(h.get("source_path") or "")
            ck = str(h.get("chunk_id") or "")
            if nid in seen:
                r = seen[nid]
                r.metadata = dict(r.metadata) if r.metadata is not None else {}
                r.metadata["fts_score"] = norm
                r.final_score = min(1.0, r.final_score + 0.15 * norm)
                continue
            seen[nid] = HybridResult(
                node_id=nid,
                node_type=ntype,
                text=text,
                source_type=st,
                source_path=sp,
                chunk_id=ck,
                vector_score=0.0,
                graph_hops=0,
                final_score=0.35 * norm,
                metadata={"from_fts": True, "fts_score": norm},
            )

    def _expand_graph(self, node_id: str, node_type: str, depth: int) -> list[dict]:
        template = _GRAPH_QUERIES.get(node_type)
        if not template:
            return []
        q = template.format(d=depth)
        rows = self.gs.query(q, {"id": node_id})
        results = []
        for r in rows:
            if len(r) < 6:
                continue
            results.append(
                {
                    "node_id": str(r[0] or ""),
                    "label": r[1],
                    "text": str(r[2]) if r[2] is not None else "",
                    "source_path": str(r[3]) if r[3] is not None else "",
                    "source_type": str(r[4]) if r[4] is not None else "",
                    "node_type": str(r[5] or ""),
                }
            )
        return results

    def query(
        self,
        query_text: str,
        top_k: int = 5,
        node_type: str | None = None,
        source_type: str | None = None,
        expand_graph: bool = True,
    ) -> list[HybridResult]:
        if not isinstance(query_text, str):
            query_text = str(query_text) if query_text is not None else ""
        if isinstance(top_k, bool):
            top_k = 5
        elif not isinstance(top_k, int):
            try:
                top_k = int(top_k)
            except (TypeError, ValueError):
                top_k = 5
        top_k = max(1, min(int(top_k), 200))

        hits = self._vector_search(query_text, top_k, node_type, source_type)
        seen: dict[str, HybridResult] = {}

        # ── Seed from vector hits ─────────────────────────────────
        for h in hits:
            nid = str(h.node_id) if h.node_id is not None else ""
            if not nid:
                continue
            name = nid.split("__")[-1]
            # FIX 2: single unified external-stub suppression
            if str(h.source_path or "") == "external" and name in _EXTERNAL_STUB_NAMES:
                continue
            seen[nid] = HybridResult(
                node_id=nid,
                node_type=str(h.node_type or ""),
                text=str(h.text) if h.text is not None else "",
                source_type=str(h.source_type or ""),
                source_path=str(h.source_path or ""),
                chunk_id=str(h.chunk_id or ""),
                vector_score=float(h.score) if h.score is not None else 0.0,
                graph_hops=0,
                final_score=float(h.score) if h.score is not None else 0.0,
                metadata=h.payload if hasattr(h, "payload") else {},
            )

        self._apply_fts(query_text, seen, top_k, node_type, source_type)

        if not expand_graph:
            return sorted(seen.values(), key=lambda x: x.final_score, reverse=True)

        for hop in range(1, self.graph_depth + 1):
            seeds = [r for r in seen.values() if r.graph_hops == hop - 1]
            for direct in seeds:
                try:
                    neighbours = self._expand_graph(direct.node_id, direct.node_type, depth=hop)
                except Exception:
                    neighbours = []
                direct.neighbours = neighbours if hop == 1 else direct.neighbours

                decay_score = direct.vector_score * (self.graph_decay**hop)

                for nb in neighbours:
                    nid2 = str(nb.get("node_id") or "")
                    if not nid2 or nid2 in seen:
                        continue
                    if nb.get("source_path") == "external" and str(nb.get("label") or "") in _EXTERNAL_STUB_NAMES:
                        continue
                    nt = str(nb.get("node_type") or "")
                    if node_type and nt != str(node_type):
                        continue
                    seen[nid2] = HybridResult(
                        node_id=nid2,
                        node_type=nt,
                        text=str(nb.get("text") or ""),
                        source_type=str(nb.get("source_type") or ""),
                        source_path=str(nb.get("source_path") or ""),
                        chunk_id="",
                        vector_score=0.0,
                        graph_hops=hop,
                        final_score=decay_score,
                        metadata={
                            k: v
                            for k, v in nb.items()
                            if k not in {"node_id", "node_type", "text", "source_type", "source_path", "label"}
                        },
                    )

        return sorted(seen.values(), key=lambda x: x.final_score, reverse=True)

    def reason_over_path(self, src_id: str, dst_id: str) -> list[str]:
        """
        Find a directed path from src to dst using BFS.
        Returns list of node IDs along the path, or empty if no path exists.
        """
        from collections import deque

        visited = {src_id}
        queue = deque([(src_id, [src_id])])

        while queue:
            current, path = queue.popleft()
            if current == dst_id:
                return path

            rows = self.gs.query("MATCH (a {id:$src})-[r:CALLS]->(b) RETURN b.id", {"src": current})
            for row in rows:
                next_id = row[0]
                if next_id and next_id not in visited:
                    visited.add(next_id)
                    new_path = path + [next_id]
                    queue.append((next_id, new_path))

        return []

    def ancestor_closure(self, node_id: str, relation: str = "CALLS", max_hops: int = 10) -> list[dict]:
        """
        Compute transitive closure from a node following a relation direction.
        Returns all reachable nodes within max_hops.
        """
        if isinstance(max_hops, bool):
            max_hops = 10
        elif not isinstance(max_hops, int):
            try:
                max_hops = int(max_hops)
            except (TypeError, ValueError):
                max_hops = 10
        max_hops = max(1, min(int(max_hops), 500))

        visited = {node_id}
        results = []
        current_front = {node_id}

        for hop in range(max_hops):
            if not current_front:
                break
            next_front = set()
            for nid in current_front:
                rel_clause = {
                    "CALLS": "(a {id:$id})-[r:CALLS]->(b)",
                    "DEFINED_IN": "(a {id:$id})-[r:DEFINED_IN]->(b)",
                    "CONTAINS": "(a {id:$id})-[r:CONTAINS]->(b)",
                }.get(relation, "(a {id:$id})-[r]->(b)")

                rows = self.gs.query(f"MATCH {rel_clause} RETURN b.id, b.name, b.qualified_name", {"id": nid})
                for row in rows:
                    bid = row[0]
                    if bid and bid not in visited:
                        visited.add(bid)
                        next_front.add(bid)
                        results.append(
                            {
                                "node_id": bid,
                                "name": row[1] or "",
                                "qualified_name": row[2] or "",
                                "hops": hop + 1,
                            }
                        )
            current_front = next_front

        return results
