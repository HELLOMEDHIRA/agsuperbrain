"""
doc_extractor.py — Hierarchical section/concept extractor from Markdown.

Input:  DocParseResult (markdown text)
Output: DocExtractionResult (Section nodes + edges)

Design:
  - Parse markdown line by line — no regex soup, no LLM
  - H1/H2/H3 headings → Section nodes with parent_id
  - Bullet points (-, *, numbered) under a section → Concept nodes
  - Edges:
      CONTAINS  : Section → child Section
      CONTAINS  : Section → Concept
  - Node IDs: normalised from doc_stem + heading path

Never sends text to an LLM. Fully deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agsuperbrain.preprocessing.doc_parser import DocParseResult

# ── Domain models ─────────────────────────────────────────────────────────────


def _nid(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@dataclass
class SectionNode:
    node_id: str
    title: str
    level: int  # 1=H1, 2=H2, 3=H3
    parent_id: str | None
    source_path: str
    source_type: str
    chunk_id: str  # "doc_stem::H1 title::H2 title"


@dataclass
class ConceptNode:
    node_id: str
    text: str
    parent_id: str  # section this bullet belongs to
    source_path: str
    source_type: str
    chunk_id: str


@dataclass
class DocExtractionResult:
    doc_node_id: str
    doc_title: str
    source_path: str
    source_type: str
    sections: list[SectionNode] = field(default_factory=list)
    concepts: list[ConceptNode] = field(default_factory=list)


# ── Markdown line classifier ──────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_NUMBERED_RE = re.compile(r"^(\s*)\d+[.)]\s+(.+)$")


def _classify(line: str) -> tuple[str, int, str]:
    """
    Returns (type, level, text):
      type  = "heading" | "bullet" | "blank" | "text"
      level = heading level (1-6) or bullet indent level (0, 1, 2)
      text  = cleaned content
    """
    m = _HEADING_RE.match(line)
    if m:
        return "heading", len(m.group(1)), m.group(2).strip()

    m = _BULLET_RE.match(line) or _NUMBERED_RE.match(line)
    if m:
        indent = len(m.group(1))
        level = indent // 2
        return "bullet", level, m.group(2).strip()

    if line.strip() == "":
        return "blank", 0, ""

    return "text", 0, line.strip()


# ── DocExtractor ──────────────────────────────────────────────────────────────


class DocExtractor:
    """
    Stateless hierarchical extractor for DocParseResult.

    Usage:
        extractor = DocExtractor()
        result    = extractor.extract(doc_parse_result)
    """

    def extract(self, dr: DocParseResult) -> DocExtractionResult:
        doc_stem = _nid(dr.source_path.stem)
        doc_id = f"doc__{doc_stem}"
        result = DocExtractionResult(
            doc_node_id=doc_id,
            doc_title=dr.title,
            source_path=str(dr.source_path),
            source_type=dr.source_type,
        )

        # Stack tracks open sections per heading level
        # stack[i] = (node_id, title) for level i
        stack: list[tuple[str, str] | None] = [None] * 7  # index 0 unused

        # Current section for bullet attribution
        current_section_id: str | None = None
        concept_counter = 0

        for raw_line in dr.markdown.splitlines():
            kind, level, text = _classify(raw_line)

            if kind == "heading":
                if level < 1 or level > 6:
                    continue

                # Build chunk_id from ancestor path
                ancestors = [entry[1] for lvl in range(1, level) if (entry := stack[lvl]) is not None]
                chunk_id = "::".join([doc_stem] + ancestors + [text])
                node_id = f"{doc_stem}__{_nid(chunk_id)}"

                # Find parent: nearest filled level above
                parent_id = None
                for lvl in range(level - 1, 0, -1):
                    entry = stack[lvl]
                    if entry is not None:
                        parent_id = entry[0]
                        break
                if parent_id is None:
                    parent_id = doc_id  # root → doc node

                section = SectionNode(
                    node_id=node_id,
                    title=text,
                    level=level,
                    parent_id=parent_id,
                    source_path=str(dr.source_path),
                    source_type=dr.source_type,
                    chunk_id=chunk_id,
                )
                result.sections.append(section)

                # Update stack: clear all deeper levels
                stack[level] = (node_id, text)
                for lvl in range(level + 1, 7):
                    stack[lvl] = None

                current_section_id = node_id

            elif kind == "bullet" and current_section_id is not None:
                if not text:
                    continue
                concept_counter += 1
                cid = f"{doc_stem}__concept_{concept_counter:04d}"
                concept = ConceptNode(
                    node_id=cid,
                    text=text,
                    parent_id=current_section_id,
                    source_path=str(dr.source_path),
                    source_type=dr.source_type,
                    chunk_id=f"{doc_stem}::concept::{concept_counter}",
                )
                result.concepts.append(concept)

        return result
