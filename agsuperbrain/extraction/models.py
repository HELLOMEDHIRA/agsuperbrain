"""
models.py — Shared data models for the extraction layer.

Lives here so rule_engine, project_index, and import_resolver
can all import from this module without circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def make_node_id(source_path: str, qualified_name: str) -> str:
    import re

    stem = re.sub(r"[^a-z0-9]+", "_", Path(source_path).stem.lower()).strip("_")
    name = re.sub(r"[^a-z0-9]+", "_", qualified_name.lower()).strip("_")
    return f"{stem}__{name}"


def normalize_id(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


@dataclass
class FunctionDef:
    node_id: str
    name: str
    qualified_name: str
    source_path: str
    start_line: int
    end_line: int
    language: str
    is_method: bool = False
    class_name: str | None = None
    body: str = ""
    docstring: str = ""


@dataclass
class CallEdge:
    caller_id: str
    callee_name: str
    callee_id: str
    source_path: str
    call_line: int
    confidence: float = 1.0
    confidence_type: str = "rule"


@dataclass
class ExtractionResult:
    functions: list[FunctionDef] = field(default_factory=list)
    calls: list[CallEdge] = field(default_factory=list)
    source_path: str = ""
    language: str = ""
