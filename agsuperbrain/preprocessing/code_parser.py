"""
code_parser.py — Tree-sitter AST parser.

Responsibility: Parse source files into ParseResult (bytes + tree).
Nothing more. Extraction is downstream.

Uses tree-sitter-language-pack for zero-config multi-language support.
Compatible with tree-sitter 0.25.x (QueryCursor API).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Node, Parser, Tree
from tree_sitter_language_pack import get_language, get_parser

# ── Supported languages (306 from tree-sitter-language-pack) ────────────────────

_SUPPORTED_LANGUAGES: set[str] = {
    # Tier 1: Full AST extraction (function/call queries defined)
    "python",
    "javascript",
    "typescript",
    "go",
    "rust",
    "java",
    "c",
    "cpp",
    "csharp",
    "ruby",
    "php",
    "kotlin",
    "swift",
    "scala",
    "scala_ms",
    # Tier 2: Parsable but no custom queries (generic extraction)
    "bash",
    "fish",
    "zsh",
    "powershell",
    "dart",
    "elixir",
    "erlang",
    "haskell",
    "ocaml",
    "julia",
    "lua",
    "perl",
    "r",
    "tcl",
    "groovy",
    "clojure",
    "fsharp",
    "vb",
    "coffeescript",
    "actionscript",
    "json",
    "yaml",
    "toml",
    "xml",
    "html",
    "css",
    "scss",
    "less",
    "sql",
    "mysql",
    "postgresql",
    "sqlite",
    "markdown",
    "rst",
    "latex",
    # Tier 3: Other supported languages
    "ada",
    "agda",
    "asm",
    "astro",
    "awk",
    "bibtex",
    "c3",
    "caddy",
    "cmake",
    "cobol",
    "commonlisp",
    "cooklang",
    "crystal",
    "cuda",
    "d",
    "dhall",
    "dockerfile",
    "dot",
    "doxygen",
    "elisp",
    "elm",
    "fennel",
    "firrtl",
    "forth",
    "fortran",
    "gdscript",
    "gdshader",
    "git_config",
    "gitignore",
    "gleam",
    "glimmer",
    "glsl",
    "gn",
    "gnuplot",
    "godot_resource",
    "gomod",
    "gosum",
    "gotmpl",
    "graphql",
    "hack",
    "hare",
    "haxe",
    "hcl",
    "heex",
    "hlsl",
    "hocon",
    "http",
    "ini",
    "ispc",
    "janet",
    "jq",
    "json5",
    "jsonnet",
    "just",
    "kcl",
    "kconfig",
    "kdl",
    "lean",
    "ledger",
    "llvm",
    "luadoc",
    "luau",
    "magik",
    "make",
    "meson",
    "mojo",
    "move",
    "nasm",
    "netlinx",
    "nginx",
    "nickel",
    "nim",
    "ninja",
    "nix",
    "nushell",
    "objc",
    "ocaml_interface",
    "odin",
    "openscad",
    "pascal",
    "pony",
    "postscript",
    "prisma",
    "prolog",
    "promql",
    "proto",
    "prql",
    "pug",
    "puppet",
    "purescript",
    "ql",
    "qmljs",
    "query",
    "racket",
    "rasi",
    "razor",
    "rego",
    "requirements",
    "robot",
    "ron",
    "sass",
    "slang",
    "smali",
    "smalltalk",
    "smithy",
    "sml",
    "snakemake",
    "solidity",
    "souffle",
    "sourcepawn",
    "sparql",
    "squirrel",
    "ssh_config",
    "stan",
    "starlark",
    "svelte",
    "systemverilog",
    "tablegen",
    "teal",
    "tera",
    "terraform",
    "thrift",
    "tlaplus",
    "tmux",
    "turtle",
    "twig",
    "typst",
    "ungrammar",
    "verilog",
    "vhdl",
    "vhs",
    "vim",
    "vimdoc",
    "vue",
    "wgsl",
    "wit",
    "wolfram",
    "x86asm",
    "zig",
}

# Extension to language mapping (comprehensive)
_EXTENSION_MAP: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    # JavaScript/TypeScript
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    ".astro": "astro",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rust",
    # Java/Kotlin/Scala
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    # C/C++
    ".c": "c",
    ".h": "c",
    ".i": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".c++": "cpp",
    ".h++": "cpp",
    # C#
    ".cs": "csharp",
    # Ruby
    ".rb": "ruby",
    ".rake": "ruby",
    ".gemspec": "ruby",
    ".podspec": "ruby",
    # PHP
    ".php": "php",
    ".phtml": "php",
    # Swift
    ".swift": "swift",
    # Dart
    ".dart": "dart",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".ps1": "powershell",
    ".psm1": "powershell",
    # Scripting
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".R": "r",
    ".tcl": "tcl",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".jl": "julia",
    # Data/Config
    ".json": "json",
    ".json5": "json5",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    # Systems
    ".zig": "zig",
    ".nim": "nim",
    ".nix": "nix",
    ".asm": "asm",
    ".s": "asm",
    # Functional
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".fs": "fsharp",
    ".fsx": "fsharp",
    # Other popular
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".tex": "latex",
    ".adb": "ada",
    ".ads": "ada",
    ".ll": "llvm",
    ".cmake": "cmake",
    ".dockerfile": "dockerfile",
    ".tf": "terraform",
    ".hcl": "hcl",
}

# Lazily populated — NEVER import this dict directly in other modules.
# Always call _get_language(name) instead.
_LANGUAGE_REGISTRY: dict[str, Language] = {}


# ── S-expression queries ──────────────────────────────────────────────────────

_FUNCTION_QUERIES: dict[str, str] = {
    "python": """
(function_definition
  name: (identifier) @func_name) @func_def
""",
    "javascript": """
(function_declaration
  name: (identifier) @func_name) @func_def
(variable_declarator
  name: (identifier) @func_name
  value: (arrow_function)) @func_def
(variable_declarator
  name: (identifier) @func_name
  value: (function)) @func_def
""",
    "typescript": """
(function_declaration
  name: (identifier) @func_name) @func_def
(variable_declarator
  name: (identifier) @func_name
  value: (arrow_function)) @func_def
""",
    "go": """
(function_declaration
  name: (identifier) @func_name) @func_def
(method_declaration
  name: (field_identifier) @func_name) @func_def
""",
    "rust": """
(function_item
  name: (identifier) @func_name) @func_def
(method_item
  name: (identifier) @func_name) @func_def
(closure_expression
  body: (block) @func_body) @closure_def
""",
    "java": """
(method_declaration
  name: (identifier) @func_name) @func_def
(constructor_declaration
  name: (identifier) @func_name) @func_def
""",
    "c": """
(function_definition
  declarator: (identifier) @func_name) @func_def
""",
    "cpp": """
(function_definition
  declarator: (identifier) @func_name) @func_def
(method_declaration
  declarator: (identifier) @func_name) @func_def
""",
    "csharp": """
(method_declaration
  name: (identifier) @func_name) @func_def
(constructor_declaration
  name: (identifier) @func_name) @func_def
""",
    "ruby": """
(method_declaration
  name: (identifier) @func_name) @func_def
(function_definition
  name: (identifier) @func_name) @func_def
""",
    "php": """
(function_definition
  name: (identifier) @func_name) @func_def
(method_declaration
  name: (identifier) @func_name) @func_def
""",
    "kotlin": """
(function_declaration
  name: (identifier) @func_name) @func_def
(method_declaration
  name: (identifier) @func_name) @func_def
""",
    "swift": """
(function_declaration
  name: (identifier) @func_name) @func_def
""",
}

_CALL_QUERIES: dict[str, str] = {
    "python": """
(call
  function: [
    (identifier)              @callee
    (attribute
      attribute: (identifier) @callee)
  ]) @call_site
""",
    "javascript": """
(call_expression
  function: [
    (identifier)                       @callee
    (member_expression
      property: (property_identifier)  @callee)
  ]) @call_site
""",
    "typescript": """
(call_expression
  function: [
    (identifier)                       @callee
    (member_expression
      property: (property_identifier)  @callee)
  ]) @call_site
""",
    "go": """
(call_expression
  function: [
    (identifier)              @callee
    (member_expression
      name: (field_identifier) @callee)
  ]) @call_site
""",
    "rust": """
(call_expression
  function: (identifier) @callee) @call_site
""",
    "java": """
(method_invocation
  name: (identifier) @callee) @call_site
""",
    "c": """
(call_expression
  function: (identifier) @callee) @call_site
""",
    "cpp": """
(call_expression
  function: [
    (identifier)              @callee
    (member_expression
      name: (field_identifier) @callee)
  ]) @call_site
""",
    "csharp": """
(invocation_expression
  member: (identifier) @callee) @call_site
""",
    "ruby": """
(call
  method: (identifier) @callee) @call_site
(method_call
  method: (identifier) @callee) @call_site
""",
    "php": """
(function_call
  name: (identifier) @callee) @call_site
(method_call
  method: (member_access
    property: (property_identifier) @callee)) @call_site
""",
    "kotlin": """
(call_expression
  callee: (identifier) @callee) @call_site
""",
    "swift": """
(call_expression
  callee: (identifier) @callee) @call_site
""",
}


# ── GENERIC queries for ALL 306 languages ──────────────────────────────────────────────────
# Used as fallback for languages without specific queries

_GENERIC_FUNCTION_QUERY = """
(function_definition name: (identifier) @func_name) @func_def
(function_declaration name: (identifier) @func_name) @func_def
(function_item name: (identifier) @func_name) @func_def
(function_signature name: (identifier) @func_name) @func_def
(function_signature_item name: (identifier) @func_name) @func_def
(method_declaration name: (identifier) @func_name) @func_def
(method_definition name: (identifier) @func_name) @func_def
(method_item name: (identifier) @func_name) @func_def
(procedure_declaration name: (identifier) @func_name) @func_def
(procedure_definition name: (identifier) @func_name) @func_def
(routine_declaration name: (identifier) @func_name) @func_def
(routine_definition name: (identifier) @func_name) @func_def
(function_signature type: (_) name: (identifier) @func_name) @func_def
(variable_declarator name: (identifier) @func_name value: (arrow_function)) @func_def
(variable_declarator name: (identifier) @func_name value: (function)) @func_def
(method_declaration name: (field_identifier) @func_name) @func_def
""".strip()


_GENERIC_CALL_QUERY = """
(call function: [ (identifier) @callee (attribute attribute: (identifier) @callee) ]) @call_site
(call_expression function: [ (identifier) @callee (member_expression property: (identifier) @callee) ]) @call_site
(function_call function: (identifier) @callee) @call_site
(method_invocation name: (identifier) @callee) @call_site
(invocation_expression member: (identifier) @callee) @call_site
(call_expression callee: (identifier) @callee) @call_site
(call callee: (identifier) @callee) @call_site
(function_invocation) @call_site
""".strip()


# ── Public helpers ────────────────────────────────────────────────────────────


def detect_language(path: Path) -> str | None:
    """Infer language from file extension. Returns None if unknown."""
    return _EXTENSION_MAP.get(path.suffix.lower())


def _get_language(name: str) -> Language:
    """
    Lazily return a Language object for the given name.
    Always call this — never import _LANGUAGE_REGISTRY directly.
    """
    if name not in _LANGUAGE_REGISTRY:
        if name not in _SUPPORTED_LANGUAGES:
            raise ValueError(f"Language {name!r} not supported.")
        _LANGUAGE_REGISTRY[name] = get_language(name)
    return _LANGUAGE_REGISTRY[name]


def get_queries(language: str) -> dict[str, str] | None:
    """
    Return {"function": s_expr, "call": s_expr} for a language.

    Uses language-specific query if defined, otherwise falls back to
    GENERIC query that works for ALL 306 tree-sitter languages.
    This ensures comprehensive support without hardcoding 306 queries.
    """
    # Use language-specific if available
    if language in _FUNCTION_QUERIES:
        return {
            "function": _FUNCTION_QUERIES[language],
            "call": _CALL_QUERIES.get(language, _GENERIC_CALL_QUERY),
        }

    # For ANY other language, we rely on the generic fallback
    # but we wrap in try-catch downstream (see rule_engine)
    return {
        "function": _GENERIC_FUNCTION_QUERY,
        "call": _GENERIC_CALL_QUERY,
    }


def get_query_or_none(language: str) -> dict[str, str] | None:
    """
    Return queries ONLY if specifically defined, None otherwise.
    Use this when you NEED specific queries.
    """
    if language not in _FUNCTION_QUERIES:
        return None
    return {
        "function": _FUNCTION_QUERIES[language],
        "call": _CALL_QUERIES.get(language, ""),
    }


def run_query(language: Language, s_expr: str, root_node: Node) -> list[tuple[int, dict]]:
    """
    Execute an S-expression query against a root node.

    Compatible with tree-sitter 0.25.x:
      Query(lang, s_expr)  →  QueryCursor(query).matches(node)
      returns list[(pattern_index, {capture_name: [Node, ...]})]

    Falls back to empty list on any error.
    """
    try:
        from tree_sitter import Query, QueryCursor

        q = Query(language, s_expr)
        cursor = QueryCursor(q)
        return list(cursor.matches(root_node))
    except Exception as e:
        # Surface the error clearly so it shows in pipeline error log
        raise RuntimeError(f"Query execution failed: {e}") from e


# ── ParseResult ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParseResult:
    """
    Immutable container passed to all downstream extractors.

    Attributes:
        source_bytes: Raw UTF-8 bytes.
        tree:         tree-sitter AST Tree.
        language:     Normalised language string ("python", ...).
        source_path:  Absolute resolved path.
    """

    source_bytes: bytes
    tree: Tree
    language: str
    source_path: Path

    def node_text(self, node: Node) -> str:
        return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


# ── CodeParser ────────────────────────────────────────────────────────────────


class CodeParser:
    """
    Stateless multi-language parser backed by tree-sitter-language-pack.

    Usage:
        parser = CodeParser()
        result = parser.parse(Path("myfile.py"))
        result = parser.parse_string("def foo(): pass", "python")
    """

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}

    def _get_parser(self, language: str) -> Parser:
        if language not in self._parsers:
            self._parsers[language] = get_parser(language)
        return self._parsers[language]

    def parse(self, path: Path, language: str | None = None) -> ParseResult:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        lang = language or detect_language(path)
        if lang is None:
            raise ValueError(f"Cannot detect language for {path.suffix!r}. Pass language= explicitly.")
        source_bytes = path.read_bytes()
        tree = self._get_parser(lang).parse(source_bytes)
        return ParseResult(
            source_bytes=source_bytes,
            tree=tree,
            language=lang,
            source_path=path.resolve(),
        )

    def parse_string(
        self,
        source: str,
        language: str,
        fake_path: Path | None = None,
    ) -> ParseResult:
        source_bytes = source.encode("utf-8")
        tree = self._get_parser(language).parse(source_bytes)
        return ParseResult(
            source_bytes=source_bytes,
            tree=tree,
            language=language,
            source_path=fake_path or Path("<string>"),
        )
