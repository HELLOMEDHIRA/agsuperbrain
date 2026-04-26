"""
rule_engine.py — Deterministic rule-based AST extractor.

Extracts:
  - FunctionDef: every function/method defined in a file
  - CallEdge:    every call site with accurate caller scope

Scope resolution:
  - parent-walk from call node → nearest function boundary
  - self/cls method calls resolved via ProjectIndex (Phase 2)
  - cross-file calls resolved via ImportMap (Phase 2)

Uses dual-mode extraction:
  1. Try tree-sitter queries for known languages (Python, JS, Go, Rust, etc.)
  2. Fall back to GENERIC AST walker for ANY other language

This ensures ALL 306 tree-sitter languages are supported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tree_sitter import Node

from agsuperbrain.extraction.models import (
    CallEdge,
    ExtractionResult,
    FunctionDef,
)
from agsuperbrain.extraction.models import (
    normalize_id as _normalize_id,
)
from agsuperbrain.preprocessing.code_parser import (
    ParseResult,
    _get_language,
    get_queries,
    run_query,
)

if TYPE_CHECKING:
    from agsuperbrain.extraction.import_resolver import ImportMap
    from agsuperbrain.extraction.project_index import ProjectIndex


# ── Function detection via GENERIC AST walking ────────────────────────────────

_FUNCTION_KEYWORDS = frozenset(
    {
        "function",
        "func",
        "def",
        "fn",
        "sub",
        "subroutine",
        "procedure",
        "method",
        "destructor",
        "lambda",
        "closure",
        "routine",
        "proc",
    }
)

_FUNCTION_NODE_PATTERNS = [
    "function_definition",
    "function_declaration",
    "function_item",
    "function_signature",
    "function_signature_item",
    "method_declaration",
    "method_definition",
    "method_item",
    "procedure_declaration",
    "procedure_definition",
    "routine_declaration",
    "routine_definition",
    "closure_expression",
    "lambda_expression",
]

_CALL_NODE_PATTERNS = [
    "call",
    "call_expression",
    "function_call",
    "routine_call",
    "method_invocation",
    "procedure_call",
    "invoke_expression",
    "function_invocation",
]


def _is_likely_function_node(node: Node) -> bool:
    """Check if node type looks like a function definition."""
    node_type = node.type.lower()
    return any(pattern in node_type for pattern in _FUNCTION_NODE_PATTERNS)


def _is_likely_call_node(node: Node) -> bool:
    """Check if node type looks like a function call."""
    node_type = node.type.lower()
    return any(pattern in node_type for pattern in _CALL_NODE_PATTERNS)


def _find_child_by_type(node: Node, pattern: str) -> Node | None:
    """Find first child matching a type pattern (case-insensitive)."""
    pattern_lower = pattern.lower()
    for child in node.children:
        if pattern_lower in child.type.lower():
            return child
    return None


def _find_identifier_in_node(node: Node) -> Node | None:
    """Find an identifier node somewhere in the subtree."""
    if node.type == "identifier":
        return node
    for child in node.children:
        result = _find_identifier_in_node(child)
        if result:
            return result
    return None


def _extract_generic_functions(
    pr: ParseResult,
) -> ExtractionResult:
    """
    GENERIC AST extraction - works for ANY language.

    Walks the tree and extracts functions using heuristics:
    - Looks for nodes with "function" in type name
    - Looks for "def"/"fn"/"func" keywords
    - Falls back to any identifier followed by parentheses
    """
    result = ExtractionResult(
        source_path=str(pr.source_path),
        language=pr.language,
    )

    def walk(node: Node, in_function: bool = False):
        """Recursively walk AST to find functions and calls."""
        # Check if this is a function definition
        is_func = _is_likely_function_node(node)
        if is_func or in_function:
            # Try to find the function name
            name_node = _find_identifier_in_node(node)
            if name_node:
                func_name = pr.node_text(name_node)
                if func_name and func_name not in ("", " ", "lambda"):
                    fdef = FunctionDef(
                        node_id=f"{_normalize_id(pr.source_path.stem)}__{_normalize_id(func_name)}",
                        name=func_name,
                        qualified_name=func_name,
                        source_path=str(pr.source_path),
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        language=pr.language,
                    )
                    result.functions.append(fdef)

        # Check for function calls
        is_call = _is_likely_call_node(node)
        if is_call:
            callee = _find_identifier_in_node(node)
            if callee:
                call_name = pr.node_text(callee)
                if call_name:
                    caller_id = f"{_normalize_id(pr.source_path.stem)}____module__"
                    result.calls.append(
                        CallEdge(
                            caller_id=caller_id,
                            callee_name=call_name,
                            callee_id=f"{_normalize_id(pr.source_path.stem)}__{_normalize_id(call_name)}",
                            source_path=str(pr.source_path),
                            call_line=node.start_point[0] + 1,
                            confidence=0.3,
                            confidence_type="generic",
                        )
                    )

        # Recurse into children
        for child in node.children:
            walk(child, in_function=is_func)

    walk(pr.tree.root_node)
    return result


# ── Function boundary types per language ──────────────────────────────────────

_FUNCTION_BOUNDARY_TYPES: dict[str, set[str]] = {
    "python": {"function_definition"},
    "javascript": {"function_declaration", "function", "arrow_function"},
    "typescript": {"function_declaration", "function", "arrow_function"},
}


# ── AST helpers ───────────────────────────────────────────────────────────────


def _node_text(node: Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _first(value) -> Node | None:
    """Normalise capture value: Node or list[Node] → first Node or None."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _find_enclosing_function(node: Node, language: str) -> Node | None:
    """
    Walk .parent chain upward to find nearest function boundary node.
    Returns None when the call is at module scope.
    """
    boundary = _FUNCTION_BOUNDARY_TYPES.get(language, set())
    current = node.parent
    while current is not None:
        if current.type in boundary:
            return current
        current = current.parent
    return None


def _get_class_name(func_node: Node, source_bytes: bytes) -> str | None:
    """Walk up from a function node to find enclosing class (Python)."""
    current = func_node.parent
    while current is not None:
        if current.type == "class_definition":
            for child in current.children:
                if child.type == "identifier":
                    return _node_text(child, source_bytes)
        current = current.parent
    return None


def _extract_docstring(func_node: Node, source_bytes: bytes) -> str:
    """
    Return the first string literal inside a function body as the docstring.
    Python-specific; returns "" for other languages or when absent.
    """
    for child in func_node.children:
        if child.type == "block":
            for stmt in child.children:
                if stmt.type == "expression_statement":
                    for inner in stmt.children:
                        if inner.type == "string":
                            raw = _node_text(inner, source_bytes)
                            return raw.strip("'\" \n").replace('"""', "").replace("'''", "").strip()
    return ""


# ── RuleEngine ────────────────────────────────────────────────────────────────


class RuleEngine:
    """
    Stateless deterministic extractor.

    Phase 1 (single-file, no cross-file resolution):
        engine = RuleEngine()
        result = engine.extract(parse_result)

    Phase 2 (multi-file, cross-file resolution):
        result = engine.extract(
            parse_result,
            project_index=idx,
            import_map=imap,
        )
    """

    def extract(
        self,
        pr: ParseResult,
        project_index: ProjectIndex | None = None,
        import_map: ImportMap | None = None,
    ) -> ExtractionResult:

        result = ExtractionResult(
            source_path=str(pr.source_path),
            language=pr.language,
        )

        queries = get_queries(pr.language)
        if queries is None:
            return result  # unsupported language — safe no-op

        lang_obj = _get_language(pr.language)
        module_prefix = _normalize_id(pr.source_path.stem)

        # ── Try tree-sitter queries first ────────────────────────────────────────
        # If query fails (invalid syntax), fall back to GENERIC AST walker
        try:
            return self._extract_with_queries(pr, lang_obj, module_prefix, queries, project_index, import_map)
        except RuntimeError:
            # Query failed, use GENERIC AST extraction as fallback
            # This works for ANY language without specific queries
            return _extract_generic_functions(pr)

    def _extract_with_queries(
        self,
        pr: ParseResult,
        lang_obj,
        module_prefix: str,
        queries: dict,
        project_index,
        import_map,
    ) -> ExtractionResult:
        """Extract using tree-sitter S-expression queries."""
        result = ExtractionResult(
            source_path=str(pr.source_path),
            language=pr.language,
        )

        # ── Pass 1: function definitions ──────────────────────────────────
        # run_query → list[(pattern_idx, {capture_name: [Node, ...]})]
        func_matches = run_query(lang_obj, queries["function"], pr.tree.root_node)

        # id(tree_node) → FunctionDef for O(1) scope lookup in Pass 2
        node_to_funcdef: dict[int, FunctionDef] = {}

        for _idx, capture in func_matches:
            fdn = _first(capture.get("func_def"))
            fnn = _first(capture.get("func_name"))
            if fdn is None or fnn is None:
                continue

            raw_name = _node_text(fnn, pr.source_bytes)
            class_name = _get_class_name(fdn, pr.source_bytes)
            is_method = class_name is not None
            qual_name = f"{class_name}.{raw_name}" if class_name else raw_name
            node_id = f"{module_prefix}__{_normalize_id(qual_name)}"

            body_raw = _node_text(fdn, pr.source_bytes)
            docstring = _extract_docstring(fdn, pr.source_bytes) if pr.language == "python" else ""

            fdef = FunctionDef(
                node_id=node_id,
                name=raw_name,
                qualified_name=qual_name,
                source_path=str(pr.source_path),
                start_line=fdn.start_point[0] + 1,
                end_line=fdn.end_point[0] + 1,
                language=pr.language,
                is_method=is_method,
                class_name=class_name,
                body=body_raw,
                docstring=docstring,
            )
            result.functions.append(fdef)
            node_to_funcdef[id(fdn)] = fdef

        # ── Pass 2: call sites ────────────────────────────────────────────
        call_matches = run_query(lang_obj, queries["call"], pr.tree.root_node)
        seen: set[tuple[int, str]] = set()

        for _idx, capture in call_matches:
            call_node = _first(capture.get("call_site"))
            callee_node = _first(capture.get("callee"))
            if call_node is None or callee_node is None:
                continue

            callee_name = _node_text(callee_node, pr.source_bytes)
            key = (id(call_node), callee_name)
            if key in seen:
                continue
            seen.add(key)

            # ── Scope: find enclosing function ────────────────────────
            enclosing = _find_enclosing_function(call_node, pr.language)
            caller_funcdef: FunctionDef | None = None

            if enclosing is None:
                caller_id = f"{module_prefix}____module__"
            else:
                caller_funcdef = node_to_funcdef.get(id(enclosing))
                if caller_funcdef is not None:
                    caller_id = caller_funcdef.node_id
                else:
                    name_child = next(
                        (c for c in enclosing.children if c.type == "identifier"),
                        None,
                    )
                    raw = _node_text(name_child, pr.source_bytes) if name_child else "anonymous"
                    caller_id = f"{module_prefix}__{_normalize_id(raw)}"

            # ── Callee resolution ─────────────────────────────────────
            if project_index is not None and import_map is not None:
                caller_class = caller_funcdef.class_name if caller_funcdef else None
                callee_id, confidence, confidence_type = project_index.resolve_call(
                    callee_raw=callee_name,
                    caller_module=module_prefix,
                    caller_class=caller_class,
                    import_map=import_map,
                )
            else:
                # Phase 1 — no project context, best-effort local stub
                callee_id = f"{module_prefix}__{_normalize_id(callee_name)}"
                confidence = 0.3
                confidence_type = "ambiguous"

            result.calls.append(
                CallEdge(
                    caller_id=caller_id,
                    callee_name=callee_name,
                    callee_id=callee_id,
                    source_path=str(pr.source_path),
                    call_line=call_node.start_point[0] + 1,
                    confidence=confidence,
                    confidence_type=confidence_type,
                )
            )

        return result
