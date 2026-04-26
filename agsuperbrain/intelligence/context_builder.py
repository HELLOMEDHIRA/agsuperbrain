"""
context_builder.py — Converts HybridResults into a compact text bundle for the LLM.

Rules (per architecture spec):
- NEVER send full documents to LLM
- Prioritize: direct edges → critical paths → summaries
- Enforce token limit (~1500 words / ~6000 chars)
- Include function signature + docstring + body preview
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePath

from agsuperbrain.intelligence.retriever import HybridResult

_MAX_CONTEXT_CHARS = 5500  # safe buffer under 2048-token context window
_MAX_PER_NODE_CHARS = 600  # per node snippet cap


@dataclass
class EvidenceItem:
    node_id: str
    node_type: str
    text: str
    source_path: str
    score: float
    graph_hops: int
    body: str = ""
    docstring: str = ""


@dataclass
class ContextBundle:
    context_text: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    token_estimate: int = 0


def _node_to_snippet(r: HybridResult) -> str:
    """
    Build a readable snippet for one node.
    Includes: type, name, source file, body preview.
    """
    src = PurePath(r.source_path).name if r.source_path else "unknown"
    body = (r.metadata or {}).get("body", "")
    docstring = (r.metadata or {}).get("docstring", "")

    lines = [f"[{r.node_type}] {r.text}  (source: {src})"]
    if docstring:
        lines.append(f"  Docstring: {docstring[:200]}")
    if body:
        # Include up to 400 chars of body — enough for the LLM to see logic
        lines.append(f"  Body:\n{body[:400]}")
    return "\n".join(lines)


class ContextBuilder:
    """
    Converts a ranked list of HybridResults into a minimal context string
    suitable for the LLM.

    Priority ordering (already handled by retriever scoring):
      1. High vector-score, 0-hop nodes (direct semantic matches)
      2. Low-hop graph neighbours (structural context)
      3. Everything else (filler, usually cut by char limit)
    """

    def build(
        self,
        results: list[HybridResult],
        query: str,
        max_chars: int = _MAX_CONTEXT_CHARS,
    ) -> ContextBundle:
        evidence: list[EvidenceItem] = []
        snippets: list[str] = []
        total_chars = 0

        for r in results:
            # Skip external stubs — they have no body and add noise
            if r.source_path == "external":
                continue

            snippet = _node_to_snippet(r)
            snippet = snippet[:_MAX_PER_NODE_CHARS]

            if total_chars + len(snippet) > max_chars:
                break  # budget exhausted

            snippets.append(snippet)
            total_chars += len(snippet)

            meta = r.metadata or {}
            evidence.append(
                EvidenceItem(
                    node_id=r.node_id,
                    node_type=r.node_type,
                    text=r.text,
                    source_path=r.source_path,
                    score=round(r.final_score, 4),
                    graph_hops=r.graph_hops,
                    body=meta.get("body", "") or "",
                    docstring=meta.get("docstring", "") or "",
                )
            )

        context_text = "\n\n".join(snippets) if snippets else ""
        token_estimate = total_chars // 4  # rough approximation

        return ContextBundle(
            context_text=context_text,
            evidence=evidence,
            token_estimate=token_estimate,
        )
