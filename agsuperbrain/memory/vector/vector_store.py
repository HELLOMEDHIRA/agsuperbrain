"""
vector_store.py — Qdrant local-mode persistence and search.

Responsibility: upsert VectorPoints, run semantic queries.
Storage: on-disk via QdrantClient(path=...) — no Docker, no server.
Collection schema: cosine distance, 384-dim, rich payload.

FIX: VectorPoint uses field name `id` (not `point_id`) so it matches
     PointStruct(id=...) and avoids __init__ kwarg mismatch.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

COLLECTION = "superbrain_nodes"


@dataclass
class VectorPoint:
    """One embeddable unit ready for Qdrant."""

    id: int
    vector: list[float]
    node_id: str
    node_type: str
    text: str
    source_type: str
    source_path: str
    chunk_id: str
    body: str = ""
    docstring: str = ""


@dataclass
class SearchResult:
    """One search hit returned to callers."""

    score: float
    node_id: str
    node_type: str
    text: str
    source_type: str
    source_path: str
    chunk_id: str
    payload: dict = field(default_factory=dict)


class VectorStore:
    """
    Qdrant local-mode vector store.

    No Docker required. Data persists to db_path on disk.

    Usage:
        vs = VectorStore(db_path=Path("./.agsuperbrain/qdrant"))
        vs.ensure_collection(384)
        vs.upsert([VectorPoint(id=1, vector=[...], ...)])
        results = vs.search(query_vector, limit=5)
    """

    def __init__(
        self,
        db_path: Path = Path("./.agsuperbrain/qdrant"),
        collection_name: str = COLLECTION,
    ) -> None:
        self.collection_name = collection_name
        db_path = Path(db_path)
        db_path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(db_path))

    # ── Collection management ─────────────────────────────────────────────

    def ensure_collection(self, vector_size: int) -> None:
        """Create collection if it does not exist (idempotent)."""
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection_name not in existing:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )

    def delete_collection(self) -> None:
        """Wipe all vectors — use before full re-indexing."""
        self.client.delete_collection(self.collection_name)

    def count(self) -> int:
        """Total points currently in the collection."""
        return self.client.count(self.collection_name).count

    def delete_by_source_path(self, source_path: str) -> int:
        """
        Delete all vectors that came from a source_path.
        Returns count of deleted points.
        """
        try:
            result = self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="source_path",
                            match=MatchValue(value=source_path),
                        )
                    ]
                ),
            )
            return result if isinstance(result, int) else 0
        except Exception as exc:
            warnings.warn(
                f"Qdrant delete_by_source_path({source_path!r}) failed: {exc}",
                stacklevel=2,
            )
            return 0

    def delete_by_node_id(self, node_id: str) -> int:
        """Delete a single point by node_id."""
        try:
            result = self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="node_id",
                            match=MatchValue(value=node_id),
                        )
                    ]
                ),
            )
            return result if isinstance(result, int) else 0
        except Exception as exc:
            warnings.warn(
                f"Qdrant delete_by_node_id({node_id!r}) failed: {exc}",
                stacklevel=2,
            )
            return 0

    # ── Write ─────────────────────────────────────────────────────────────

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=p.id,
                    vector=p.vector,
                    payload={
                        "node_id": p.node_id,
                        "node_type": p.node_type,
                        "text": p.text,
                        "source_type": p.source_type,
                        "source_path": p.source_path,
                        "chunk_id": p.chunk_id,
                        "body": p.body,  # ← now correct
                        "docstring": p.docstring,  # ← now correct
                    },
                )
                for p in points
            ],
            wait=True,
        )

    # ── Read ──────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        limit: int = 5,
        node_type: str | None = None,
        source_type: str | None = None,
    ) -> list[SearchResult]:
        """
        Semantic nearest-neighbour search with optional payload filters.

        Args:
            query_vector: 384-dim L2-normalised float vector.
            limit:        Top-k results to return.
            node_type:    Filter by node type:
                          Function | Section | Concept | Transcript
            source_type:  Filter by source type:
                          code | document | audio | external

        Returns:
            list of SearchResult sorted by descending cosine score.
        """
        if isinstance(limit, bool):
            limit = 5
        elif not isinstance(limit, int):
            try:
                limit = int(limit)  # JSON/MCP may pass a string
            except (TypeError, ValueError):
                limit = 5
        limit = max(1, min(int(limit), 200))

        must = []
        if node_type:
            must.append(
                FieldCondition(
                    key="node_type",
                    match=MatchValue(value=str(node_type).capitalize()),
                )
            )
        if source_type:
            must.append(
                FieldCondition(
                    key="source_type",
                    match=MatchValue(value=str(source_type).lower()),
                )
            )

        query_filter = Filter(must=must) if must else None

        try:
            hits = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter,
            ).points
        except ValueError as e:
            if "not found" in str(e).lower():
                raise RuntimeError(
                    f"Qdrant collection '{self.collection_name}' is missing. "
                    "Run `superbrain index-vectors` to embed graph nodes first."
                ) from e
            raise

        def _ps(v: object, default: str = "") -> str:
            if v is None:
                return default
            if isinstance(v, str):
                return v
            return str(v)

        results = []
        for h in hits:
            payload = h.payload or {}
            results.append(
                SearchResult(
                    score=float(h.score) if h.score is not None else 0.0,
                    node_id=_ps(payload.get("node_id", "")),
                    node_type=_ps(payload.get("node_type", "")),
                    text=_ps(payload.get("text", "")),
                    source_type=_ps(payload.get("source_type", "")),
                    source_path=_ps(payload.get("source_path", "")),
                    chunk_id=_ps(payload.get("chunk_id", "")),
                    payload=payload,  # full passthrough for body/docstring
                )
            )
        return results
