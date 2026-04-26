"""
tools.py — MCP-style tool layer.

Each tool:
  1. Retrieves via HybridRetriever
  2. Builds context via ContextBuilder
  3. Generates answer via LlamaEngine (optional)
  4. Returns ToolResponse { answer, evidence, confidence }

LLM is optional — if model_path not set, falls back to
deterministic bullet-list answer (Phase 6 behaviour).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from agsuperbrain.intelligence.context_builder import ContextBuilder, EvidenceItem
from agsuperbrain.intelligence.retriever import HybridRetriever


@dataclass
class ToolResponse:
    answer: str
    evidence: list[dict]
    confidence: float
    used_llm: bool = False

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 4),
            "used_llm": self.used_llm,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def _evidence_to_dicts(items: list[EvidenceItem]) -> list[dict]:
    return [
        {
            "node_id": e.node_id,
            "node_type": e.node_type,
            "text": e.text,
            "source_path": e.source_path,
            "score": e.score,
            "graph_hops": e.graph_hops,
            "is_stub": e.source_path == "external",
            "body": e.body,
            "docstring": e.docstring,
        }
        for e in items
    ]


def _fallback_answer(evidence: list[EvidenceItem], query: str) -> str:
    """Deterministic answer when LLM is unavailable."""
    real = [e for e in evidence if e.source_path != "external"]
    if not real:
        return f"No relevant information found for: {query}"
    bullets = "\n".join(f"- [{e.source_path.split('/')[-1]}] {e.text[:180]}" for e in real[:3])
    return f"Found {len(real)} relevant node(s):\n{bullets}"


def _merge_confidence(llm_conf: float, vector_top: float) -> float:
    """Blend LLM self-reported confidence with retrieval score."""
    return round(min((llm_conf * 0.6 + vector_top * 0.4), 1.0), 4)


class SuperBrainTools:
    """
    MCP-style tool layer.

    If llm_engine is provided → LLM answers.
    If not → deterministic bullet-list fallback (Phase 6 mode).
    """

    def __init__(
        self,
        retriever: HybridRetriever,
        context_builder: ContextBuilder,
        top_k: int = 5,
        llm_engine=None,  # Optional[LlamaEngine]
    ) -> None:
        self.retriever = retriever
        self.context_builder = context_builder
        self.top_k = top_k
        self.llm = llm_engine

    def _run(
        self,
        query: str,
        node_type: str | None = None,
        source_type: str | None = None,
    ) -> ToolResponse:
        results = self.retriever.query(
            query,
            top_k=self.top_k,
            node_type=node_type,
            source_type=source_type,
        )
        bundle = self.context_builder.build(results, query=query)
        top_score = results[0].final_score if results else 0.0
        evidence = _evidence_to_dicts(bundle.evidence)

        # ── LLM path ────────────────────────────────────────────────────
        if self.llm is not None and bundle.context_text.strip():
            resp = self.llm.answer(bundle.context_text, query)
            conf = _merge_confidence(resp.confidence, top_score)
            return ToolResponse(
                answer=resp.answer,
                evidence=evidence,
                confidence=conf,
                used_llm=resp.used_llm,
            )

        # ── Deterministic fallback ───────────────────────────────────────
        return ToolResponse(
            answer=_fallback_answer(bundle.evidence, query),
            evidence=evidence,
            confidence=round(top_score * 0.8, 4),
            used_llm=False,
        )

    def search(self, query: str) -> ToolResponse:
        return self._run(query)

    def code_tool(self, query: str) -> ToolResponse:
        return self._run(query, node_type="Function")

    def audio_tool(self, query: str) -> ToolResponse:
        return self._run(query, node_type="Transcript")

    def document_tool(self, query: str) -> ToolResponse:
        rs = self.retriever.query(query, top_k=self.top_k, node_type="Section")
        rc = self.retriever.query(query, top_k=self.top_k, node_type="Concept")
        merged = {r.node_id: r for r in rs + rc}
        all_r = sorted(merged.values(), key=lambda x: x.final_score, reverse=True)
        bundle = self.context_builder.build(all_r, query=query)
        top_score = all_r[0].final_score if all_r else 0.0

        if self.llm is not None and bundle.context_text.strip():
            resp = self.llm.answer(bundle.context_text, query)
            conf = _merge_confidence(resp.confidence, top_score)
            return ToolResponse(
                answer=resp.answer,
                evidence=_evidence_to_dicts(bundle.evidence),
                confidence=conf,
                used_llm=resp.used_llm,
            )
        return ToolResponse(
            answer=_fallback_answer(bundle.evidence, query),
            evidence=_evidence_to_dicts(bundle.evidence),
            confidence=round(top_score * 0.8, 4),
            used_llm=False,
        )
