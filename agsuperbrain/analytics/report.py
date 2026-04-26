"""
report.py — GRAPH_REPORT.md generator.

Pure-Cypher analytics over KùzuDB. No external analytics deps.

Sections emitted:
  1. Stats                      — node/edge counts across phases
  2. God-nodes by in-degree     — most-called functions
  3. God-nodes by out-degree    — most-calling functions (orchestrators)
  4. Cross-module dependencies  — caller module → callee module call counts
  5. Orphan modules             — modules with no incoming cross-module calls
  6. Suggested questions        — templated, derived from god-nodes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from agsuperbrain.memory.graph.graph_store import GraphStore

_TOP_N = 10


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class ReportData:
    stats: dict[str, int] = field(default_factory=dict)
    god_in: list[tuple[str, str, int]] = field(default_factory=list)
    god_out: list[tuple[str, str, int]] = field(default_factory=list)
    cross_module: list[tuple[str, str, int]] = field(default_factory=list)
    orphan_modules: list[tuple[str, str]] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)


# ── Collectors ───────────────────────────────────────────────────────────────


def _collect_stats(gs: GraphStore) -> dict[str, int]:
    queries = [
        ("Modules", "MATCH (m:Module)          RETURN count(m)"),
        ("Functions", "MATCH (f:Function)        RETURN count(f)"),
        ("Call edges", "MATCH ()-[r:CALLS]->()    RETURN count(r)"),
        ("Documents", "MATCH (d:Document)        RETURN count(d)"),
        ("Sections", "MATCH (s:Section)         RETURN count(s)"),
        ("Concepts", "MATCH (c:Concept)         RETURN count(c)"),
        ("Audio sources", "MATCH (a:AudioSource)     RETURN count(a)"),
        ("Transcript segs", "MATCH (t:Transcript)      RETURN count(t)"),
    ]
    out: dict[str, int] = {}
    for label, q in queries:
        rows = gs.query(q)
        out[label] = int(rows[0][0]) if rows else 0
    return out


def _collect_god_in(gs: GraphStore, limit: int = _TOP_N) -> list[tuple[str, str, int]]:
    rows = gs.query(
        "MATCH (caller:Function)-[:CALLS]->(f:Function) "
        "RETURN f.qualified_name, f.source_path, count(caller) AS n "
        "ORDER BY n DESC LIMIT " + str(limit)
    )
    return [(r[0] or "<unknown>", r[1] or "", int(r[2])) for r in rows]


def _collect_god_out(gs: GraphStore, limit: int = _TOP_N) -> list[tuple[str, str, int]]:
    rows = gs.query(
        "MATCH (f:Function)-[:CALLS]->(callee:Function) "
        "RETURN f.qualified_name, f.source_path, count(callee) AS n "
        "ORDER BY n DESC LIMIT " + str(limit)
    )
    return [(r[0] or "<unknown>", r[1] or "", int(r[2])) for r in rows]


def _collect_cross_module(gs: GraphStore) -> list[tuple[str, str, int]]:
    rows = gs.query(
        "MATCH (src:Function)-[:DEFINED_IN]->(m_src:Module), "
        "      (src)-[:CALLS]->(dst:Function)-[:DEFINED_IN]->(m_dst:Module) "
        "WHERE m_src.id <> m_dst.id "
        "RETURN m_src.name, m_dst.name, count(*) AS n "
        "ORDER BY n DESC"
    )
    return [(r[0] or "", r[1] or "", int(r[2])) for r in rows]


def _collect_orphan_modules(gs: GraphStore) -> list[tuple[str, str]]:
    # Modules whose functions receive no CALLS from functions in other modules.
    rows = gs.query(
        "MATCH (m:Module) "
        "WHERE NOT EXISTS { "
        "  MATCH (f:Function)-[:DEFINED_IN]->(m), "
        "        (caller:Function)-[:CALLS]->(f), "
        "        (caller)-[:DEFINED_IN]->(m_other:Module) "
        "  WHERE m_other.id <> m.id "
        "} "
        "RETURN m.name, m.source_path"
    )
    return [(r[0] or "", r[1] or "") for r in rows]


def _build_suggested_questions(
    god_in: list[tuple[str, str, int]],
    god_out: list[tuple[str, str, int]],
    orphans: list[tuple[str, str]],
) -> list[str]:
    qs: list[str] = []
    if god_in and len(god_in) >= 1:
        top = god_in[0][0]
        qs.append(f"What does {top} do?")
        qs.append(f"Who calls {top}?")
    if god_in and len(god_in) >= 2:
        qs.append(f"Explain the role of {god_in[1][0]} in the system.")
    if god_out and len(god_out) >= 1:
        top = god_out[0][0]
        qs.append(f"What does {top} depend on?")
    if god_out and len(god_out) >= 2:
        qs.append(f"Trace the call path starting from {god_out[1][0]}.")
    if orphans and len(orphans) >= 1:
        for m_name, _ in orphans[:2]:
            qs.append(f"Is the `{m_name}` module an entry point or dead code?")
    return qs


# ── Assembly ─────────────────────────────────────────────────────────────────


def collect(gs: GraphStore) -> ReportData:
    data = ReportData(
        stats=_collect_stats(gs),
        god_in=_collect_god_in(gs),
        god_out=_collect_god_out(gs),
        cross_module=_collect_cross_module(gs),
        orphan_modules=_collect_orphan_modules(gs),
    )
    data.suggested_questions = _build_suggested_questions(
        data.god_in,
        data.god_out,
        data.orphan_modules,
    )
    return data


# ── Rendering ────────────────────────────────────────────────────────────────


def _fmt_path(p: str) -> str:
    if not p:
        return ""
    return Path(p).name


def render_markdown(data: ReportData) -> str:
    lines: list[str] = []
    lines.append("# GRAPH_REPORT")
    lines.append("")
    lines.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")

    # 1. Stats
    lines.append("## 1. Stats")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---:|")
    for k, v in data.stats.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # 2. God-nodes by in-degree
    lines.append(f"## 2. Top {_TOP_N} functions by in-degree (most called)")
    lines.append("")
    if data.god_in:
        lines.append("| # | Function | File | Incoming calls |")
        lines.append("|---:|---|---|---:|")
        for i, (name, path, n) in enumerate(data.god_in, 1):
            lines.append(f"| {i} | `{name}` | {_fmt_path(path)} | {n} |")
    else:
        lines.append("_No CALLS edges in the graph yet._")
    lines.append("")

    # 3. God-nodes by out-degree
    lines.append(f"## 3. Top {_TOP_N} functions by out-degree (most calling)")
    lines.append("")
    if data.god_out:
        lines.append("| # | Function | File | Outgoing calls |")
        lines.append("|---:|---|---|---:|")
        for i, (name, path, n) in enumerate(data.god_out, 1):
            lines.append(f"| {i} | `{name}` | {_fmt_path(path)} | {n} |")
    else:
        lines.append("_No CALLS edges in the graph yet._")
    lines.append("")

    # 4. Cross-module dependencies
    lines.append("## 4. Cross-module call dependencies")
    lines.append("")
    if data.cross_module:
        lines.append("| From module | → | To module | Calls |")
        lines.append("|---|---|---|---:|")
        for src, dst, n in data.cross_module:
            lines.append(f"| `{src}` | → | `{dst}` | {n} |")
    else:
        lines.append("_No cross-module calls detected._")
    lines.append("")

    # 5. Orphan modules
    lines.append("## 5. Orphan modules (no incoming cross-module calls)")
    lines.append("")
    if data.orphan_modules:
        lines.append("| Module | Path |")
        lines.append("|---|---|")
        for name, path in data.orphan_modules:
            lines.append(f"| `{name}` | {path} |")
        lines.append("")
        lines.append("_Orphans are either entry points (CLI, main, tests) or dead code._")
    else:
        lines.append("_Every module is reachable from at least one other._")
    lines.append("")

    # 6. Suggested questions
    lines.append("## 6. Suggested questions")
    lines.append("")
    if data.suggested_questions:
        for q in data.suggested_questions:
            lines.append(f"- {q}")
    else:
        lines.append("_Not enough graph data yet to derive questions._")
    lines.append("")

    return "\n".join(lines)


def generate_report(gs: GraphStore) -> str:
    return render_markdown(collect(gs))
