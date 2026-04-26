"""
import_resolver.py — Deterministic import statement extractor.

Extracts the local-name → source-module mapping from a ParseResult.
Used by rule_engine Pass B to resolve cross-file call targets.

Supported:
  Python:
    import utils                     → utils       → utils
    from utils import connect         → connect     → utils
    from utils import connect as conn → conn        → utils
    from .db import query             → query       → db  (relative, best-effort)

  JavaScript / TypeScript:
    import { connect } from './utils' → connect     → utils
    import connect from './utils'     → connect     → utils
    const x = require('./utils')      → x           → utils
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tree_sitter import Node

from agsuperbrain.preprocessing.code_parser import ParseResult


@dataclass
class ImportRecord:
    local_name: str  # name used in this file
    source_module: str  # normalised module stem (e.g. "utils", "db")
    source_path: str  # original import string (e.g. "./utils", "myapp.db")


@dataclass
class ImportMap:
    """All imports extracted from one file."""

    records: list[ImportRecord] = field(default_factory=list)

    def resolve(self, local_name: str) -> str | None:
        """Return source_module for a local_name, or None if not imported."""
        for r in self.records:
            if r.local_name == local_name:
                return r.source_module
        return None


def _module_stem(import_str: str) -> str:
    """
    Best-effort extraction of the base module name from an import string.

    Examples:
        "myapp.utils"    → "utils"
        "./db/connection"→ "connection"
        "from .models"   → "models"
    """
    # strip leading dots (relative imports)
    s = import_str.lstrip(".")
    # take last segment of dotted path or path sep
    s = re.split(r"[./\\]", s)[-1]
    return s.lower() if s else import_str.lower()


def _text(node: Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


# ── Python import walker ──────────────────────────────────────────────────────


def _walk_python_imports(node: Node, src: bytes, records: list[ImportRecord]) -> None:
    """Recursively collect Python import_statement and import_from_statement nodes."""

    if node.type == "import_statement":
        # import foo, import foo as bar
        for child in node.children:
            if child.type == "dotted_name":
                name = _text(child, src)
                stem = _module_stem(name)
                records.append(ImportRecord(stem, stem, name))
            elif child.type == "aliased_import":
                # import foo as bar
                original = next((_text(c, src) for c in child.children if c.type == "dotted_name"), "")
                alias = next(
                    (_text(c, src) for c in child.children if c.type == "identifier" and c != child.children[0]), ""
                )
                stem = _module_stem(original)
                if alias:
                    records.append(ImportRecord(alias, stem, original))
                else:
                    records.append(ImportRecord(stem, stem, original))

    elif node.type == "import_from_statement":
        # from foo import bar, baz
        # from foo import bar as b
        module_node = next((c for c in node.children if c.type in ("dotted_name", "relative_import")), None)
        module_str = _text(module_node, src) if module_node else ""
        stem = _module_stem(module_str)

        for child in node.children:
            if child.type == "import_prefix":
                continue
            if child.type == "dotted_name" and child is module_node:
                continue
            if child.type == "identifier":
                local = _text(child, src)
                records.append(ImportRecord(local, stem, module_str))
            elif child.type == "aliased_import":
                original_name = next((_text(c, src) for c in child.children if c.type == "identifier"), "")
                alias = next((_text(c, src) for c in reversed(child.children) if c.type == "identifier"), "")
                records.append(ImportRecord(alias or original_name, stem, module_str))

    for child in node.children:
        _walk_python_imports(child, src, records)


# ── JavaScript / TypeScript import walker ────────────────────────────────────


def _walk_js_imports(node: Node, src: bytes, records: list[ImportRecord]) -> None:
    """Collect JS/TS import declarations, require(), and dynamic import()."""

    if node.type == "import_declaration":
        # Find source string  "from './utils'"
        source_node = next((c for c in node.children if c.type == "string"), None)
        if source_node is None:
            for child in node.children:
                _walk_js_imports(child, src, records)
            return

        raw_src = _text(source_node, src).strip("'\"")
        stem = _module_stem(raw_src)

        for child in node.children:
            # import defaultExport from '...'
            if child.type == "identifier":
                records.append(ImportRecord(_text(child, src), stem, raw_src))
            # import { foo, bar as b } from '...'
            elif child.type == "import_clause":
                for sub in child.children:
                    if sub.type == "named_imports":
                        for spec in sub.children:
                            if spec.type == "import_specifier":
                                names = [
                                    _text(c, src)
                                    for c in spec.children
                                    if c.type in ("identifier", "property_identifier")
                                ]
                                # last name is the local alias if aliased
                                local = names[-1] if names else ""
                                if local:
                                    records.append(ImportRecord(local, stem, raw_src))
                    elif sub.type == "identifier":
                        records.append(ImportRecord(_text(sub, src), stem, raw_src))

    elif node.type == "lexical_declaration":
        # const x = require('./foo')
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = next((c for c in child.children if c.type == "identifier"), None)
                val_node = next((c for c in child.children if c.type == "call_expression"), None)
                if name_node and val_node:
                    func = next((c for c in val_node.children if c.type == "identifier"), None)
                    if func and _text(func, src) == "require":
                        arg = next((c for c in val_node.children if c.type == "arguments"), None)
                        if arg:
                            str_node = next((c for c in arg.children if c.type == "string"), None)
                            if str_node:
                                raw = _text(str_node, src).strip("'\"")
                                stem = _module_stem(raw)
                                records.append(ImportRecord(_text(name_node, src), stem, raw))

    # Dynamic import(): import('./foo')
    elif node.type == "import":
        for child in node.children:
            if child.type == "arguments":
                for arg in child.children:
                    if arg.type == "string":
                        raw = _text(arg, src).strip("'\"")
                        stem = _module_stem(raw)
                        # Dynamic imports return a Promise, so we track the module path
                        # The resolved exports would be accessed via .then()
                        records.append(ImportRecord(stem, stem, raw))

    for child in node.children:
        _walk_js_imports(child, src, records)


# ── Public API ────────────────────────────────────────────────────────────────

_WALKERS = {
    "python": _walk_python_imports,
    "javascript": _walk_js_imports,
    "typescript": _walk_js_imports,
}


def extract_imports(pr: ParseResult) -> ImportMap:
    """
    Extract all import records from a ParseResult.

    Returns an ImportMap for use in cross-file call resolution.
    Unknown languages return an empty ImportMap (safe no-op).
    """
    walker = _WALKERS.get(pr.language)
    records: list[ImportRecord] = []
    if walker:
        walker(pr.tree.root_node, pr.source_bytes, records)
    return ImportMap(records=records)
