"""RQ1: agreement with a reference static call-graph analyser (code2flow).

We do NOT claim absolute extraction accuracy. Instead, we measure agreement
between Super-Brain's CALLS edges and code2flow's call graph for the same
Python source tree. Disagreements are inspected to understand cause:
each tool has known blind spots (decorators, dynamic dispatch, imports
through aliases, generic call wrappers) and their union is informative.

Both extractors operate on the SAME source tree. We canonicalise function
identifiers to (file_basename, class_or_none, name) tuples so the
heterogeneous naming conventions of the two tools become comparable.

Usage (from ~/agsbrepo, after run_eval.py has built the index):
    python paper/evaluation/run_rq1.py \\
        --repo . --target-dir agsuperbrain \\
        --out paper/evaluation/results_rq1.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

CanonId = tuple[str, str, str]  # (file_basename, class_or_empty, name)


def canon_from_sb(name: str, class_name: str | None, source_path: str) -> CanonId | None:
    """Build the canonical identifier from a Super-Brain Function row."""
    if not name or name in {"<module>", "<lambda>"}:
        return None
    base = Path(source_path).stem
    cls = class_name or ""
    return (base, cls, name)


_C2F_NAME_RE = re.compile(r"^(?P<file>[^:]+)::(?:(?P<cls>[^.]+)\.)?(?P<name>[^.]+)$")


def canon_from_c2f(c2f_name: str) -> CanonId | None:
    """Parse a code2flow node 'name' field into (file, class, fname)."""
    if not c2f_name:
        return None
    # code2flow can also produce bare names for module-level pseudo nodes,
    # like '(global)' — skip those.
    if "::" not in c2f_name:
        return None
    m = _C2F_NAME_RE.match(c2f_name)
    if not m:
        return None
    fname = m.group("name")
    if fname in {"(global)", "<module>", "__init__"} and not m.group("cls"):
        # module-level pseudo-nodes — skip; SB has its own `<module>` form
        return None
    return (m.group("file"), m.group("cls") or "", fname)


def collect_sb_edges(repo: Path, target_subdir: str) -> tuple[set[tuple[CanonId, CanonId]], set[CanonId]]:
    """Return (edge set, function set) from the Super-Brain graph,
    restricted to .py files inside `target_subdir` (relative to repo)."""
    from agsuperbrain.memory.graph.graph_store import GraphStore

    gs = GraphStore(repo / ".agsuperbrain" / "graph")
    gs.init_schema()

    target_prefix = str((repo / target_subdir).resolve())

    # All Function nodes inside target_subdir, .py only
    rows = gs.query(
        "MATCH (f:Function) "
        "WHERE f.source_path STARTS WITH $p AND f.source_path ENDS WITH '.py' "
        "RETURN f.id, f.name, f.class_name, f.source_path",
        {"p": target_prefix},
    )
    id_to_canon: dict[str, CanonId] = {}
    func_set: set[CanonId] = set()
    for r in rows:
        c = canon_from_sb(str(r[1] or ""), str(r[2] or ""), str(r[3] or ""))
        if c is None:
            continue
        id_to_canon[str(r[0])] = c
        func_set.add(c)

    # CALLS edges where both endpoints are in our func set
    rows = gs.query(
        "MATCH (c:Function)-[:CALLS]->(t:Function) "
        "WHERE c.source_path STARTS WITH $p AND t.source_path STARTS WITH $p "
        "AND c.source_path ENDS WITH '.py' AND t.source_path ENDS WITH '.py' "
        "RETURN c.id, t.id",
        {"p": target_prefix},
    )
    edges: set[tuple[CanonId, CanonId]] = set()
    for r in rows:
        cid = str(r[0])
        tid = str(r[1])
        if cid in id_to_canon and tid in id_to_canon:
            edges.add((id_to_canon[cid], id_to_canon[tid]))
    return edges, func_set


def collect_c2f_edges(c2f_bin: str, target_dir: Path, work_dir: Path) -> tuple[set[tuple[CanonId, CanonId]], set[CanonId], dict]:
    """Run code2flow on target_dir, parse JSON, return (edge set, function set, raw stats)."""
    out = work_dir / "c2f.json"
    cmd = [
        c2f_bin,
        str(target_dir),
        "--language", "py",
        "--output", str(out),
        "--skip-parse-errors",
        "--quiet",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"code2flow failed: rc={res.returncode}\nstdout={res.stdout}\nstderr={res.stderr}")

    raw = json.loads(out.read_text())
    g = raw.get("graph", raw)
    nodes_raw = g.get("nodes", {})
    edges_raw = g.get("edges", [])

    id_to_canon: dict[str, CanonId] = {}
    func_set: set[CanonId] = set()
    for node_id, node in nodes_raw.items():
        c = canon_from_c2f(node.get("name", ""))
        if c is None:
            continue
        id_to_canon[node_id] = c
        func_set.add(c)

    edges: set[tuple[CanonId, CanonId]] = set()
    for e in edges_raw:
        s = e.get("source")
        t = e.get("target")
        if s in id_to_canon and t in id_to_canon:
            edges.add((id_to_canon[s], id_to_canon[t]))

    stats = {
        "raw_nodes": len(nodes_raw),
        "raw_edges": len(edges_raw),
        "canon_nodes": len(func_set),
        "canon_edges": len(edges),
    }
    return edges, func_set, stats


def fmt_canon(c: CanonId) -> str:
    f, cls, name = c
    return f"{f}::{cls + '.' if cls else ''}{name}"


def disagreement_examples(edges_a: set, edges_b: set, label_a: str, label_b: str, k: int = 10):
    """Return up to k example edges in A but not B, with caller frequency ranking."""
    diff = edges_a - edges_b
    callers = Counter(c for c, _t in diff)
    examples: list[str] = []
    seen_callers: set = set()
    for caller, _cnt in callers.most_common():
        for c, t in diff:
            if c == caller:
                examples.append(f"{fmt_canon(c)} -> {fmt_canon(t)}")
                seen_callers.add(caller)
                break
        if len(examples) >= k:
            break
    return examples


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--target-dir", default="agsuperbrain",
                    help="subdirectory under --repo to compare (default: agsuperbrain)")
    ap.add_argument("--out", type=Path, default=Path("paper/evaluation/results_rq1.json"))
    ap.add_argument("--c2f-bin", default=os.environ.get("CODE2FLOW_BIN", "code2flow"))
    args = ap.parse_args()

    repo = args.repo.resolve()
    target_dir = (repo / args.target_dir).resolve()
    if not target_dir.exists():
        print(f"ERROR: target dir does not exist: {target_dir}", file=sys.stderr)
        return 2

    work_dir = repo / ".agsuperbrain" / "rq1_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    print(f"[rq1] running code2flow on {target_dir}", flush=True)
    t0 = time.perf_counter()
    c2f_edges, c2f_funcs, c2f_stats = collect_c2f_edges(args.c2f_bin, target_dir, work_dir)
    c2f_seconds = time.perf_counter() - t0

    print(f"[rq1] reading Super-Brain graph", flush=True)
    sb_edges, sb_funcs = collect_sb_edges(repo, args.target_dir)

    # Restrict comparison to the intersection of the function-id spaces.
    # If a function is invisible to one tool, edges touching it can't be
    # adjudicated — including them would just penalise whichever tool sees
    # more functions.
    common_funcs = sb_funcs & c2f_funcs
    sb_edges_in = {(c, t) for c, t in sb_edges if c in common_funcs and t in common_funcs}
    c2f_edges_in = {(c, t) for c, t in c2f_edges if c in common_funcs and t in common_funcs}

    tp = sb_edges_in & c2f_edges_in
    sb_only = sb_edges_in - c2f_edges_in   # SB has, code2flow doesn't
    c2f_only = c2f_edges_in - sb_edges_in  # code2flow has, SB doesn't

    # If we treat code2flow as the reference (RQ1 protocol uses an
    # "independent static analyser"), then:
    #   precision (SB) = TP / (TP + sb_only)    -- of edges SB emits, how many code2flow agrees with
    #   recall    (SB) = TP / (TP + c2f_only)   -- of code2flow's edges, how many SB also emits
    p = len(tp) / max(1, len(tp) + len(sb_only))
    r = len(tp) / max(1, len(tp) + len(c2f_only))
    f1 = (2 * p * r) / max(1e-9, p + r)

    sb_only_examples = disagreement_examples(sb_edges_in, c2f_edges_in, "SB", "c2f")
    c2f_only_examples = disagreement_examples(c2f_edges_in, sb_edges_in, "c2f", "SB")

    result = {
        "meta": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "target_dir": str(target_dir),
            "reference_analyser": "code2flow 2.5.1",
            "python": sys.version.split()[0],
            "framing": (
                "Agreement with code2flow as reference. Both extractors "
                "are static analysers with known blind spots; this is "
                "NOT a measurement against absolute ground truth."
            ),
        },
        "code2flow_runtime_seconds": round(c2f_seconds, 3),
        "code2flow_raw": c2f_stats,
        "function_sets": {
            "sb_functions": len(sb_funcs),
            "c2f_functions": len(c2f_funcs),
            "common_functions": len(common_funcs),
        },
        "edge_sets_restricted_to_common_funcs": {
            "sb_edges": len(sb_edges_in),
            "c2f_edges": len(c2f_edges_in),
            "true_positive": len(tp),
            "sb_only": len(sb_only),
            "c2f_only": len(c2f_only),
        },
        "agreement_metrics": {
            "precision_sb_vs_c2f": round(p, 4),
            "recall_sb_vs_c2f": round(r, 4),
            "f1_sb_vs_c2f": round(f1, 4),
        },
        "disagreement_examples": {
            "sb_only_top": sb_only_examples,
            "c2f_only_top": c2f_only_examples,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print(f"[rq1] wrote {args.out}", flush=True)
    print(json.dumps(result["agreement_metrics"], indent=2))
    print(json.dumps(result["edge_sets_restricted_to_common_funcs"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
