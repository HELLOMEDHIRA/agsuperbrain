"""MCP stdio server: graph and vector tools (MCP spec)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import sleep, time

from agsuperbrain.terminal import TEXT_ENCODING

_gs = None
_vs = None
_emb = None


def _get_store(db_path: str = "./.agsuperbrain/graph"):
    global _gs
    if _gs is None:
        from agsuperbrain.memory.graph.graph_store import GraphStore

        _gs = GraphStore(Path(db_path))
        _gs.init_schema()
    return _gs


def _get_vs(qdrant_path: str = "./.agsuperbrain/qdrant"):
    global _vs
    if _vs is None:
        from agsuperbrain.memory.vector.vector_store import VectorStore

        _vs = VectorStore(Path(qdrant_path))
    return _vs


def _get_retriever(db_path: str = "./.agsuperbrain/graph", qdrant_path: str = "./.agsuperbrain/qdrant"):
    """Lazy `HybridRetriever`; always import the class here (avoids UnboundLocalError on repeat calls)."""
    global _emb
    if _emb is None:
        from agsuperbrain.memory.vector.embedder import TextEmbedder

        _emb = TextEmbedder()
    from agsuperbrain.intelligence.retriever import HybridRetriever

    return HybridRetriever(_get_store(db_path), _get_vs(qdrant_path), _emb)


TOOLS = {}


def tool(name: str):
    """Decorator to register a tool handler."""

    def decorator(func):
        TOOLS[name] = func
        return func

    return decorator


# MCP `initialize` response (tools-only)
CAPABILITIES = {
    "tools": {},
}


def _tool_str(v: object, default: str = "") -> str:
    if v is None:
        return default
    if isinstance(v, str):
        return v
    return str(v)


def _tool_int(v: object, default: int, *, min_v: int = 1, max_v: int = 200) -> int:
    if isinstance(v, bool):
        return default
    if not isinstance(v, (int, float, str)):
        return default
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(n, max_v))


def _status_path_from_db(db_path: str) -> Path:
    """Resolve `db_path` to `.agsuperbrain/watcher.status.json` for common graph layouts."""
    p = Path(db_path)
    try:
        p = p.resolve()
    except OSError:
        pass
    if p.is_dir() and p.name == "graph" and p.parent.name == ".agsuperbrain":
        return p.parent / "watcher.status.json"
    if p.name == "superbrain.db" and p.parent.name == "graph" and p.parent.parent.name == ".agsuperbrain":
        return p.parent.parent / "watcher.status.json"
    if p.name == "graph" and p.parent.name == ".agsuperbrain":
        return p.parent / "watcher.status.json"
    for parent in [p, *p.parents]:
        if parent.name == ".agsuperbrain":
            return parent / "watcher.status.json"
    return Path(".agsuperbrain") / "watcher.status.json"


def _read_watcher_status(db_path: str) -> dict:
    sp = _status_path_from_db(db_path)
    if not sp.exists():
        return {"ok": False, "error": "status file not found", "status_path": str(sp)}
    try:
        data = json.loads(sp.read_text(encoding=TEXT_ENCODING))
    except Exception as exc:
        return {"ok": False, "error": f"could not read status file: {exc}", "status_path": str(sp)}
    data = data if isinstance(data, dict) else {"raw": data}
    data["ok"] = True
    data["status_path"] = str(sp)
    return data


@tool("search_code")
def search_code(
    query: str,
    limit: int = 5,
    mode: str = "all",
    db_path: str = "./.agsuperbrain/graph",
    qdrant_path: str = "./.agsuperbrain/qdrant",
) -> dict:
    """Semantic code search."""
    q = _tool_str(query)
    lim = _tool_int(limit, 5)
    m = _tool_str(mode, "all").lower()
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    qp = _tool_str(qdrant_path, "./.agsuperbrain/qdrant")

    ret = _get_retriever(dbp, qp)
    node_type = None
    if m == "code":
        node_type = "Function"
    elif m == "document":
        node_type = "Section"
    elif m == "audio":
        node_type = "Transcript"

    results = ret.query(q, top_k=lim, node_type=node_type)
    return {
        "index_state": _read_watcher_status(dbp),
        "results": [
            {
                "node_id": r.node_id,
                "text": r.text,
                "source_path": r.source_path,
                "score": r.final_score,
                "graph_hops": r.graph_hops,
            }
            for r in results
        ],
    }


@tool("watcher_status")
def watcher_status(db_path: str = "./.agsuperbrain/graph") -> dict:
    """Return watcher status (pending queue, last flush) if available."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    return _read_watcher_status(dbp)


@tool("await_index_idle")
def await_index_idle(
    timeout_s: float = 5.0,
    poll_s: float = 0.2,
    db_path: str = "./.agsuperbrain/graph",
) -> dict:
    """
    Wait until watcher state is idle (or timeout). This prevents stale reads when
    an agent queries immediately after writing files.
    """
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    deadline = time() + max(0.1, float(timeout_s))
    interval = max(0.05, float(poll_s))
    last = _read_watcher_status(dbp)
    while time() < deadline:
        if last.get("ok") and last.get("state") in (None, "idle"):
            return {"ok": True, "idle": True, "status": last}
        sleep(interval)
        last = _read_watcher_status(dbp)
    return {"ok": bool(last.get("ok")), "idle": False, "status": last, "timeout_s": timeout_s}


@tool("find_callers")
def find_callers(function_id: str, db_path: str = "./.agsuperbrain/graph") -> dict:
    """Find all functions that call the given function."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    rows = gs.query(
        "MATCH (caller:Function)-[:CALLS]->(callee:Function {id:$fid}) "
        "RETURN caller.id, caller.qualified_name, caller.source_path",
        {"fid": function_id},
    )
    return {
        "index_state": _read_watcher_status(dbp),
        "callers": [{"id": r[0], "qualified_name": r[1], "source_path": r[2]} for r in rows],
    }


@tool("find_callees")
def find_callees(function_id: str, db_path: str = "./.agsuperbrain/graph") -> dict:
    """Find all functions called by the given function."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    rows = gs.query(
        "MATCH (caller:Function {id:$fid})-[:CALLS]->(callee:Function) "
        "RETURN callee.id, callee.qualified_name, callee.source_path",
        {"fid": function_id},
    )
    return {
        "index_state": _read_watcher_status(dbp),
        "callees": [{"id": r[0], "qualified_name": r[1], "source_path": r[2]} for r in rows],
    }


@tool("get_function_body")
def get_function_body(qualified_name: str, db_path: str = "./.agsuperbrain/graph") -> dict:
    """Get function body and docstring."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    rows = gs.query(
        "MATCH (f:Function) "
        "WHERE f.qualified_name = $q OR f.name = $q "
        "RETURN f.id, f.qualified_name, f.source_path, f.start_line, f.end_line, "
        "       f.is_method, f.class_name, f.docstring, f.body",
        {"q": qualified_name},
    )
    if not rows:
        return {"index_state": _read_watcher_status(dbp), "error": f"Function not found: {qualified_name}"}
    r = rows[0]
    return {
        "index_state": _read_watcher_status(dbp),
        "id": r[0],
        "qualified_name": r[1],
        "source_path": r[2],
        "start_line": r[3],
        "end_line": r[4],
        "is_method": r[5],
        "class_name": r[6],
        "docstring": r[7],
        "body": r[8],
    }


@tool("path_between")
def path_between(src_id: str, dst_id: str, db_path: str = "./.agsuperbrain/graph") -> dict:
    """Find path between two functions."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    ret = _get_retriever(dbp, "./.agsuperbrain/qdrant")
    path = ret.reason_over_path(_tool_str(src_id), _tool_str(dst_id))
    return {"index_state": _read_watcher_status(dbp), "path": path}


@tool("closure")
def closure(node_id: str, relation: str = "CALLS", max_hops: int = 10, db_path: str = "./.agsuperbrain/graph") -> dict:
    """Get transitive closure from a node."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    ret = _get_retriever(dbp, "./.agsuperbrain/qdrant")
    hops = _tool_int(max_hops, 10, min_v=1, max_v=500)
    results = ret.ancestor_closure(_tool_str(node_id), _tool_str(relation, "CALLS"), hops)
    return {"index_state": _read_watcher_status(dbp), "nodes": results}


@tool("get_subgraph")
def get_subgraph(root_id: str, depth: int = 2, db_path: str = "./.agsuperbrain/graph") -> dict:
    """Get subgraph around a root node."""
    d = _tool_int(depth, 2, min_v=1, max_v=50)
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    nodes, edges = gs.get_subgraph(_tool_str(root_id), d)
    return {"index_state": _read_watcher_status(dbp), "nodes": nodes, "edges": edges}


@tool("stats")
def stats(db_path: str = "./.agsuperbrain/graph") -> dict:
    """Get graph statistics."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    metrics = {}
    for label, q in [
        ("modules", "MATCH (m:Module) RETURN count(m)"),
        ("functions", "MATCH (f:Function) RETURN count(f)"),
        ("calls", "MATCH ()-[:CALLS]->() RETURN count(*)"),
        ("documents", "MATCH (d:Document) RETURN count(d)"),
        ("sections", "MATCH (s:Section) RETURN count(s)"),
        ("concepts", "MATCH (c:Concept) RETURN count(c)"),
        ("transcripts", "MATCH (t:Transcript) RETURN count(t)"),
    ]:
        rows = gs.query(q)
        metrics[label] = rows[0][0] if rows else 0
    return {"index_state": _read_watcher_status(dbp), "metrics": metrics}


@tool("list_modules")
def list_modules(db_path: str = "./.agsuperbrain/graph") -> dict:
    """List all modules."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    rows = gs.query("MATCH (m:Module) RETURN m.id, m.name, m.source_path")
    return {
        "index_state": _read_watcher_status(dbp),
        "modules": [{"id": r[0], "name": r[1], "source_path": r[2]} for r in rows],
    }


@tool("list_functions")
def list_functions(module_id: str | None = None, db_path: str = "./.agsuperbrain/graph") -> dict:
    """List all functions, optionally filtered by module."""
    dbp = _tool_str(db_path, "./.agsuperbrain/graph")
    gs = _get_store(dbp)
    if module_id:
        rows = gs.query(
            "MATCH (f:Function)-[:DEFINED_IN]->(m:Module {id:$mid}) RETURN f.id, f.name, f.qualified_name, f.is_method",
            {"mid": module_id},
        )
    else:
        rows = gs.query("MATCH (f:Function) RETURN f.id, f.name, f.qualified_name, f.is_method")
    return {
        "index_state": _read_watcher_status(dbp),
        "functions": [{"id": r[0], "name": r[1], "qualified_name": r[2], "is_method": r[3]} for r in rows],
    }


def _server_info_version() -> str:
    try:
        from importlib.metadata import version

        return version("agsuperbrain")
    except Exception:
        return "0.1.0"


def _jsonrpc_result(request_id: object, result: object) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_request(req: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns None for notifications (no body on stdout)."""
    is_notification = "id" not in req
    method = req.get("method")
    params: dict = req.get("params") or {}
    request_id = req.get("id")

    if is_notification:
        # e.g. notifications/initialized — JSON-RPC has no response for notifications
        return None

    if method == "initialize":
        # MUST echo a protocol version the client can accept
        # https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle
        client_version = params.get("protocolVersion") or "2024-11-05"
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": client_version,
                "capabilities": CAPABILITIES,
                "serverInfo": {
                    "name": "agsuperbrain",
                    "version": _server_info_version(),
                },
            },
        )

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if method == "tools/list":
        import inspect

        tool_list = []
        for name, func in TOOLS.items():
            sig = inspect.signature(func)
            props = {}
            required = []
            for pname, p in sig.parameters.items():
                if pname in ("db_path", "qdrant_path"):
                    continue
                props[pname] = {"type": "string"}
                if p.default is inspect.Parameter.empty:
                    required.append(pname)
            tool_list.append(
                {
                    "name": name,
                    "description": func.__doc__ or "",
                    "inputSchema": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                }
            )
        return _jsonrpc_result(request_id, {"tools": tool_list})

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        if tool_name not in TOOLS:
            return _jsonrpc_error(request_id, -32601, f"Unknown tool: {tool_name!r}")
        try:
            result = TOOLS[tool_name](**tool_args)
            return _jsonrpc_result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False},
            )
        except Exception as e:
            return _jsonrpc_error(request_id, -32603, str(e))

    if method in TOOLS:
        try:
            return _jsonrpc_result(request_id, TOOLS[method](**params))
        except Exception as e:
            return _jsonrpc_error(request_id, -32603, str(e))

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method!r}")


def main():
    """Run the MCP server."""
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print("agsuperbrain-mcp 0.1.0")
        return

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                ),
                flush=True,
            )
            continue

        if not isinstance(req, dict):
            print(
                json.dumps(_jsonrpc_error(None, -32600, "Request must be a JSON object")),
                flush=True,
            )
            continue

        resp = _handle_request(req)
        if resp is not None:
            print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()
