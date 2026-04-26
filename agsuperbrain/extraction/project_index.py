"""
project_index.py — Project-wide function resolution index.

Built in Pass A (all files → FunctionDefs).
Used in Pass B (all calls → resolve callee_id).

Resolution priority:
  1. self.X  / cls.X  → look up enclosing class in same module
  2. local name match → same module function
  3. imported name    → source module function via ImportMap
  4. fallback         → bare normalised stub id (external/unresolved)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agsuperbrain.extraction.models import FunctionDef


def _nid(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@dataclass
class ProjectIndex:
    """
    Immutable (after build) lookup table for the whole project.

    Keyed by:
      (module_stem, qualified_name_lower) → node_id
      (module_stem, bare_name_lower)      → node_id  (for unqualified calls)
    """

    # (module_stem, key) → node_id
    _table: dict[tuple[str, str], str] = field(default_factory=dict)
    # node_id → FunctionDef (for richer resolution)
    _defs: dict[str, FunctionDef] = field(default_factory=dict)
    # module_stem → list[FunctionDef] (for class-method lookup)
    _by_module: dict[str, list[FunctionDef]] = field(default_factory=dict)

    @classmethod
    def build(cls, all_defs: list[FunctionDef]) -> ProjectIndex:
        """
        Construct the index from a flat list of FunctionDefs
        collected across ALL files in the project.
        """
        idx = cls(
            _table={},
            _defs={},
            _by_module={},
        )
        for fdef in all_defs:
            module_stem = _nid(fdef.source_path.split("/")[-1].rsplit(".", 1)[0])
            # register by qualified name  e.g. ("app", "dataprocessor.process")
            idx._table[(module_stem, fdef.qualified_name.lower())] = fdef.node_id
            # register by bare name       e.g. ("app", "process")
            idx._table[(module_stem, fdef.name.lower())] = fdef.node_id
            idx._defs[fdef.node_id] = fdef
            idx._by_module.setdefault(module_stem, []).append(fdef)
        return idx

    def resolve_call(
        self,
        callee_raw: str,
        caller_module: str,
        caller_class: str | None,
        import_map,  # ImportMap from import_resolver
    ) -> tuple[str, float, str]:
        """
        Resolve a raw callee name → (node_id, confidence, confidence_type).

        Confidence tiers:
          1.0 / "rule"       — same-class method or same-module function match
          0.9 / "rule"       — cross-module, both import and definition verified
          0.6 / "inferred"   — import seen but definition not indexed
          0.3 / "ambiguous"  — no import match, best-effort external stub
        """
        name_lower = callee_raw.lower()

        # ── 1. self.X or cls.X inside the same class ──────────────────
        if caller_class:
            class_lower = caller_class.lower()
            qual = f"{class_lower}.{name_lower}"
            node_id = self._table.get((caller_module, qual))
            if node_id:
                return node_id, 1.0, "rule"

        # ── 2. Same-module bare name ───────────────────────────────────
        node_id = self._table.get((caller_module, name_lower))
        if node_id:
            return node_id, 1.0, "rule"

        # ── 3. Cross-file via import map ───────────────────────────────
        source_module = import_map.resolve(callee_raw)
        if source_module:
            src_stem = _nid(source_module)
            node_id = self._table.get((src_stem, name_lower))
            if node_id:
                return node_id, 0.9, "rule"
            # Import seen but definition not in project — third-party or not yet indexed
            return f"{src_stem}__{_nid(callee_raw)}", 0.6, "inferred"

        # ── 4. Fallback: external / unresolved stub ────────────────────
        return f"{caller_module}__{_nid(callee_raw)}", 0.3, "ambiguous"

    def all_defs(self) -> list[FunctionDef]:
        return list(self._defs.values())
