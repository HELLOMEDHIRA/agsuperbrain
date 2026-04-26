"""Self-contained Cytoscape.js HTML graph (interactive) from `GraphStore` or JSON export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agsuperbrain.terminal import TEXT_ENCODING, console

if TYPE_CHECKING:
    from agsuperbrain.memory.graph.graph_store import GraphStore

# CDN pins (offline HTML; no backend)
_CYTOSCAPE_CDN = "https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"
_DAGRE_CDN = "https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"
_CY_DAGRE_CDN = "https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js"


def _build_html(graph_data: dict[str, Any]) -> str:
    """Inject `graph_data` JSON into the HTML template (`__GRAPH_DATA__` placeholder)."""
    data_json = json.dumps(graph_data, ensure_ascii=False)
    html = _HTML_TEMPLATE.replace("__GRAPH_DATA__", data_json)
    return html


def visualize(
    store: GraphStore,
    output_path: Path,
    root_function_id: str | None = None,
    max_depth: int = 3,
) -> Path:
    """Write `output_path` HTML. Subgraph if `root_function_id` is set, else full graph."""
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if root_function_id:
        console.print(f"[cyan]Subgraph[/cyan] mode — root=[bold]{root_function_id}[/bold] depth={max_depth}")
        nodes, edges = store.get_subgraph(root_function_id, max_depth)
        graph_data = {"nodes": nodes, "edges": edges}
    else:
        console.print("[cyan]Full graph[/cyan] mode")
        graph_data = store.export_graph_json()

    n_nodes = len(graph_data["nodes"])
    n_edges = len(graph_data["edges"])

    if n_nodes == 0:
        console.print("[yellow]Graph is empty — run `superbrain ingest <path>` first.[/yellow]")
        return output_path

    console.print(f"  Nodes [bold]{n_nodes}[/bold]  Edges [bold]{n_edges}[/bold]")

    html = _build_html(graph_data)
    output_path.write_text(html, encoding=TEXT_ENCODING)

    console.print(f"[green]✓[/green] Written → {output_path}")
    return output_path


def visualize_from_json(json_path: Path, output_path: Path) -> Path:
    """Write `output_path` from a `GraphStore.export_graph_json` JSON file."""
    graph_data = json.loads(Path(json_path).read_text(encoding=TEXT_ENCODING))
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    html = _build_html(graph_data)
    output_path.write_text(html, encoding=TEXT_ENCODING)
    console.print(f"[green]✓[/green] {output_path}")
    return output_path


# Template: raw string + `str.replace` for `__GRAPH_DATA__` (avoids f-string `{{` in JS/CSS).

_HTML_TEMPLATE = (
    r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Super-Brain — Graph Inspector</title>
  <script src="%CYTOSCAPE%"></script>
  <script src="%DAGRE%"></script>
  <script src="%CYDAGRE%"></script>
  <style>
    :root {
      --bg:#171614;--panel:#1c1b19;--panel2:#201f1d;--border:#393836;
      --text:#cdccca;--muted:#797876;--faint:#5a5957;
      --teal:#4f98a3;--teal2:#227f8b;
      --orange:#fdab43;--red:#d163a7;--green:#6daa45;
      --ext:#b86428;--ext-bg:#321e0e;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width:100%; height:100%; overflow:hidden; background:var(--bg); color:var(--text); font-family: Inter, 'Helvetica Neue', system-ui, sans-serif; font-size:13px; }
    #app { display:grid; grid-template-columns:340px 1fr 420px; width:100%; height:100%; }
    .panel { background:var(--panel); overflow:auto; }
    .left  { border-right:1px solid var(--border); }
    .right { border-left :1px solid var(--border); }
    .section { padding:14px 16px; border-bottom:1px solid var(--border); }
    .section h3 { font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--teal); margin-bottom:10px; }
    .small   { font-size:11px; color:var(--muted); line-height:1.6; }
    .mono    { font-family:ui-monospace, 'SF Mono', Menlo, monospace; }
    .stack   { display:grid; gap:8px; }
    .row2    { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    /* stat cards */
    .stat { background:var(--panel2); border:1px solid var(--border); border-radius:10px; padding:10px 14px; }
    .stat .k { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
    .stat .v { font-size:22px; font-weight:700; margin-top:2px; }
    /* inputs */
    input, select, button { width:100%; background:#0f0e0d; color:var(--text); border:1px solid var(--border); border-radius:10px; padding:9px 12px; font-size:12px; outline:none; transition:border-color .15s, box-shadow .15s; font-family:inherit; }
    input:focus, select:focus { border-color:var(--teal); box-shadow:0 0 0 3px rgba(79,152,163,.15); }
    button { cursor:pointer; }
    button:hover { border-color:var(--teal); }
    .btn-p  { background:var(--teal2); border-color:var(--teal); color:#e8f4f5; }
    .btn-p:hover { background:#1a6b75; }
    .btn-d  { background:#2d1422; border-color:var(--red); color:#f0d7eb; }
    .btn-d:hover { background:#3d1830; }
    .btn-s  { background:var(--panel2); }
    /* cy canvas */
    #cy { width:100%; height:100%; background:radial-gradient(ellipse at 50% 40%, #1c1b19 0%, #131211 100%); }
    /* toolbar */
    .toolbar { position:absolute; top:14px; left:360px; right:440px; z-index:10; display:flex; gap:8px; align-items:center; padding:8px 12px; background:rgba(22,21,19,.88); backdrop-filter:blur(12px); border:1px solid var(--border); border-radius:14px; }
    .toolbar button { width:auto; min-width:100px; font-size:12px; padding:7px 12px; }
    /* badges */
    .badge { display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px; border:1px solid var(--border); background:var(--panel2); color:var(--text); }
    .badge.code     { border-color:var(--teal); color:#b8dde3; background:rgba(79,152,163,.1); }
    .badge.external { border-color:var(--ext);  color:#ffd0ae; background:var(--ext-bg); }
    .badge.rel      { border-color:var(--orange); color:#ffe5b8; background:rgba(253,171,67,.08); }
    /* inspector kv rows */
    .kv { display:grid; grid-template-columns:110px 1fr; gap:8px; padding:7px 0; border-bottom:1px dashed #232220; align-items:start; }
    .kv:last-child { border-bottom:none; }
    .kv .key { font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; padding-top:1px; }
    .kv .val { font-size:12px; word-break:break-word; line-height:1.5; }
    /* neighborhood list */
    .list  { display:grid; gap:6px; }
    .item  { padding:9px 12px; background:var(--panel2); border:1px solid var(--border); border-radius:10px; }
    .item .title { font-weight:600; font-size:12px; }
    .item .meta  { font-size:11px; color:var(--muted); margin-top:3px; }
    /* node browser */
    .node-list  { max-height:260px; overflow:auto; display:grid; gap:5px; margin-top:8px; }
    .node-chip  { padding:7px 10px; border-radius:8px; background:#131211; border:1px solid var(--border); cursor:pointer; }
    .node-chip:hover { border-color:var(--teal); background:#192224; }
    .node-chip .cn { font-weight:600; font-size:12px; }
    .node-chip .cs { font-size:11px; color:var(--muted); margin-top:2px; }
    /* legend */
    .legend-row { display:flex; align-items:center; gap:8px; margin-top:7px; font-size:11px; color:var(--muted); }
    .dot { width:11px; height:11px; border-radius:50%; display:inline-block; flex-shrink:0; }
    /* separator */
    .sep { height:1px; background:var(--border); margin:12px 0; }
    /* scrollbar */
    ::-webkit-scrollbar { width:5px; height:5px; }
    ::-webkit-scrollbar-track { background:var(--panel); }
    ::-webkit-scrollbar-thumb { background:var(--border); border-radius:999px; }
    ::-webkit-scrollbar-thumb:hover { background:var(--faint); }
    /* path section */
    #path-section { display:none; }
    #path-section.visible { display:block; }
  </style>
</head>
<body>
<div id="app">

  <!-- ── LEFT PANEL ──────────────────────────────────────── -->
  <aside class="panel left">

    <div class="section">
      <h3>Graph Overview</h3>
      <div class="row2">
        <div class="stat"><div class="k">Nodes</div><div class="v" id="st-nodes">0</div></div>
        <div class="stat"><div class="k">Edges</div><div class="v" id="st-edges">0</div></div>
      </div>
      <div class="row2" style="margin-top:8px">
        <div class="stat"><div class="k">Code</div><div class="v" id="st-code">0</div></div>
        <div class="stat"><div class="k">External</div><div class="v" id="st-ext">0</div></div>
      </div>
      <div class="row2" style="margin-top:8px">
        <div class="stat"><div class="k">Methods</div><div class="v" id="st-methods">0</div></div>
        <div class="stat"><div class="k">Functions</div><div class="v" id="st-fns">0</div></div>
      </div>
    </div>

    <div class="section">
      <h3>Search & Filter</h3>
      <div class="stack">
        <input id="search" placeholder="Search id / name / class / path / lang…" />
        <select id="filter-type">
          <option value="all">All node types</option>
          <option value="code">Code only</option>
          <option value="external">External only</option>
          <option value="method">Methods only</option>
          <option value="function">Standalone functions</option>
        </select>
        <select id="layout">
          <option value="cose">Force (cose)</option>
          <option value="dagre">Directed (dagre)</option>
          <option value="circle">Circle</option>
          <option value="concentric">Concentric</option>
          <option value="breadthfirst">Breadthfirst</option>
          <option value="grid">Grid</option>
        </select>
        <div class="row2"><button id="btn-layout" class="btn-p">Apply Layout</button><button id="btn-fit" class="btn-s">Fit Graph</button></div>
        <div class="row2"><button id="btn-reset" class="btn-s">Reset Filters</button><button id="btn-labels" class="btn-s">Toggle Labels</button></div>
        <div class="row2"><button id="btn-isolated" class="btn-s">Isolated Nodes</button><button id="btn-hotspots" class="btn-s">Hotspots</button></div>
        <div class="row2"><button id="btn-edgelabels" class="btn-s">Edge Labels</button><button id="btn-pathmode" class="btn-s">Path Mode</button></div>
        <button id="btn-clear" class="btn-d">Clear Selection</button>
      </div>
      <div class="small" style="margin-top:8px">Click a node or edge for full metadata. Path Mode: click two nodes to trace call path.</div>
    </div>

    <div class="section">
      <h3>Legend</h3>
      <div class="legend-row"><span class="dot" style="background:#4f98a3"></span>Code function / method</div>
      <div class="legend-row"><span class="dot" style="background:#b86428"></span>External / unresolved callee</div>
      <div class="legend-row"><span class="dot" style="background:#fdab43"></span>Selected / highlighted</div>
      <div class="legend-row"><span class="dot" style="background:#6daa45"></span>Path start / inbound</div>
      <div class="legend-row"><span class="dot" style="background:#d163a7"></span>Path end / outbound</div>
      <div class="legend-row"><span class="dot" style="background:#797876; border:1px dashed #cdccca"></span>Isolated (no edges)</div>
    </div>

    <div class="section">
      <h3>Node Browser</h3>
      <div id="node-browser" class="node-list"></div>
    </div>

  </aside>

  <!-- ── CENTRE CANVAS ───────────────────────────────────── -->
  <main style="position:relative;overflow:hidden;">
    <div class="toolbar">
      <button id="btn-zoomin">Zoom In</button>
      <button id="btn-zoomout">Zoom Out</button>
      <button id="btn-center">Center Selected</button>
      <span class="badge mono" id="status">Graph loaded</span>
    </div>
    <div id="cy"></div>
  </main>

  <!-- ── RIGHT PANEL ─────────────────────────────────────── -->
  <aside class="panel right">

    <div class="section">
      <h3>Selection Inspector</h3>
      <div class="small" id="empty-hint">Click any node or edge to inspect every stored field.</div>
      <div id="inspector"></div>
    </div>

    <div class="section">
      <h3>Neighborhood</h3>
      <div id="neighborhood" class="list"></div>
    </div>

    <div class="section" id="path-section">
      <h3>Path Debugger</h3>
      <div id="path-output" class="list"></div>
    </div>

  </aside>

</div>
<script>
// ─── data ────────────────────────────────────────────────────────────
const graphData = __GRAPH_DATA__;

// ─── init Cytoscape ──────────────────────────────────────────────────
cytoscape.use(cytoscapeDagre);

const elements = [
  ...graphData.nodes.map(n => ({
    data: {
      ...n,
      label: n.qualified_name || n.name || n.id
    }
  })),
  ...graphData.edges.map((e, i) => ({
    data: { id: 'edge_' + i, ...e, label: 'CALLS @' + (e.call_line ?? '?') }
  }))
];

const cy = cytoscape({
  container: document.getElementById('cy'),
  elements,
  wheelSensitivity: 0.18,
  layout: { name: 'cose', animate: false, fit: true, padding: 60 },
  style: [
    {
      selector: 'node',
      style: {
        'background-color': ele =>
          ele.data('source_type') === 'external' ? '#b86428' : '#4f98a3',
        'label': 'data(label)',
        'color': '#cdccca',
        'font-size': 11,
        'text-wrap': 'wrap',
        'text-max-width': 160,
        'text-valign': 'bottom',
        'text-margin-y': 8,
        'border-width': 2,
        'border-color': '#393836',
        'width':  ele => Math.max(28, Math.min(90, 24 + ele.connectedEdges().length * 6)),
        'height': ele => Math.max(28, Math.min(90, 24 + ele.connectedEdges().length * 6)),
        'overlay-opacity': 0,
        'text-background-opacity': 1,
        'text-background-color': '#131211',
        'text-background-padding': 4,
        'text-background-shape': 'roundrectangle'
      }
    },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'width': 1.8,
        'line-color': '#44423f',
        'target-arrow-color': '#5a5957',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.9,
        'label': '',
        'font-size': 10,
        'color': '#797876',
        'text-background-color': '#131211',
        'text-background-opacity': 1,
        'text-background-padding': 3,
        'text-rotation': 'autorotate',
        'overlay-opacity': 0
      }
    },
    { selector: '.dimmed',      style: { 'opacity': 0.12, 'text-opacity': 0.08 } },
    { selector: '.highlighted', style: { 'background-color': '#fdab43', 'line-color': '#fdab43', 'target-arrow-color': '#fdab43', 'border-color': '#fdab43', 'opacity': 1, 'z-index': 999 } },
    { selector: '.path-start',  style: { 'background-color': '#6daa45', 'border-color': '#6daa45', 'opacity': 1, 'z-index': 999 } },
    { selector: '.path-end',    style: { 'background-color': '#d163a7', 'border-color': '#d163a7', 'opacity': 1, 'z-index': 999 } },
    { selector: '.on-path',     style: { 'line-color': '#fdab43', 'target-arrow-color': '#fdab43', 'width': 3, 'z-index': 998 } },
    { selector: '.isolated',    style: { 'background-color': '#5a5957', 'border-style': 'dashed', 'border-color': '#cdccca' } },
    { selector: '.hide-label',  style: { 'label': '' } },
    { selector: '.edge-label',  style: { 'label': 'data(label)' } }
  ]
});

// ─── state ───────────────────────────────────────────────────────────
let labelsOn    = true;
let edgeLabels  = false;
let pathMode    = false;
let pathPicks   = [];
let selectedEl  = null;

// ─── helpers ─────────────────────────────────────────────────────────
const $  = id => document.getElementById(id);
const esc = s  => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function status(msg) { $('status').textContent = msg; }

function clearHL() {
  cy.elements().removeClass('dimmed highlighted path-start path-end on-path isolated');
}

function updateStats() {
  const ns = cy.nodes();
  $('st-nodes').textContent   = ns.length;
  $('st-edges').textContent   = cy.edges().length;
  $('st-code').textContent    = ns.filter(n => n.data('source_type') === 'code').length;
  $('st-ext').textContent     = ns.filter(n => n.data('source_type') === 'external').length;
  $('st-methods').textContent = ns.filter(n => !!n.data('is_method')).length;
  $('st-fns').textContent     = ns.filter(n => !n.data('is_method') && n.data('source_type') === 'code').length;
}

// ─── inspector renderer ───────────────────────────────────────────────
function renderNode(node) {
  const d = node.data();
  $('empty-hint').style.display = 'none';
  $('inspector').innerHTML = `
    <div class="badge ${d.source_type === 'external' ? 'external' : 'code'}"
         style="margin-bottom:10px">${esc(d.source_type)}</div>
    <div class="sep"></div>
    <div class="kv"><div class="key">ID</div>           <div class="val mono">${esc(d.id)}</div></div>
    <div class="kv"><div class="key">Name</div>         <div class="val">${esc(d.name)}</div></div>
    <div class="kv"><div class="key">Qualified</div>    <div class="val mono">${esc(d.qualified_name)}</div></div>
    <div class="kv"><div class="key">Class</div>        <div class="val">${esc(d.class_name || '—')}</div></div>
    <div class="kv"><div class="key">Is Method</div>    <div class="val">${d.is_method ? 'true' : 'false'}</div></div>
    <div class="kv"><div class="key">Language</div>     <div class="val">${esc(d.language || '—')}</div></div>
    <div class="kv"><div class="key">Source Type</div>  <div class="val">${esc(d.source_type || '—')}</div></div>
    <div class="kv"><div class="key">Source Path</div>  <div class="val mono" style="word-break:break-all">${esc(d.source_path || '—')}</div></div>
    <div class="kv"><div class="key">Start Line</div>   <div class="val">${esc(d.start_line ?? '—')}</div></div>
    <div class="kv"><div class="key">End Line</div>     <div class="val">${esc(d.end_line   ?? '—')}</div></div>
    <div class="kv"><div class="key">In-Degree</div>    <div class="val">${node.indegree()}  <span class="small">(called by)</span></div></div>
    <div class="kv"><div class="key">Out-Degree</div>   <div class="val">${node.outdegree()} <span class="small">(calls)</span></div></div>
    <div class="kv"><div class="key">Neighbors</div>    <div class="val">${node.neighborhood('node').length}</div></div>
  `;
}

function renderEdge(edge) {
  const d = edge.data();
  $('empty-hint').style.display = 'none';
  $('inspector').innerHTML = `
    <div class="badge rel" style="margin-bottom:10px">CALLS</div>
    <div class="sep"></div>
    <div class="kv"><div class="key">Relation</div>        <div class="val">CALLS</div></div>
    <div class="kv"><div class="key">Caller (src)</div>    <div class="val mono">${esc(d.source)}</div></div>
    <div class="kv"><div class="key">Callee (tgt)</div>    <div class="val mono">${esc(d.target)}</div></div>
    <div class="kv"><div class="key">Call Line</div>       <div class="val">${esc(d.call_line ?? '—')}</div></div>
    <div class="kv"><div class="key">Confidence</div>      <div class="val">${esc(d.confidence ?? '—')}</div></div>
    <div class="kv"><div class="key">Conf. Type</div>      <div class="val">${esc(d.confidence_type ?? '—')}</div></div>
    <div class="kv"><div class="key">Edge ID</div>         <div class="val mono">${esc(d.id)}</div></div>
    <div class="kv"><div class="key">Source Path</div>     <div class="val mono">${esc(d.source_path ?? '—')}</div></div>
  `;
}

function renderNeighborhood(node) {
  const inc = node.incomers('node');
  const out = node.outgoers('node');
  $('neighborhood').innerHTML = `
    <div class="item">
      <div class="title" style="color:#6daa45">↙ Incoming callers (${inc.length})</div>
    </div>
    ${inc.map(n => `
      <div class="item" data-chip="${esc(n.id())}">
        <div class="title mono">${esc(n.data('qualified_name') || n.id())}</div>
        <div class="meta">${esc(n.data('source_type'))} · ${esc(n.data('language'))}</div>
      </div>`).join('') || '<div class="small" style="padding:6px 0">No callers.</div>'}
    <div class="item" style="margin-top:4px">
      <div class="title" style="color:#d163a7">↗ Outgoing callees (${out.length})</div>
    </div>
    ${out.map(n => `
      <div class="item" data-chip="${esc(n.id())}">
        <div class="title mono">${esc(n.data('qualified_name') || n.id())}</div>
        <div class="meta">${esc(n.data('source_type'))} · line ${esc(node.edgesTo(n).first().data('call_line'))}</div>
      </div>`).join('') || '<div class="small" style="padding:6px 0">No callees.</div>'}
  `;
  $('neighborhood').querySelectorAll('[data-chip]').forEach(el => {
    el.style.cursor = 'pointer';
    el.addEventListener('click', () => {
      const n = cy.getElementById(el.dataset.chip);
      if (n) focusNode(n);
    });
  });
}

// ─── focus helpers ────────────────────────────────────────────────────
function focusNode(node) {
  clearHL();
  cy.elements().addClass('dimmed');
  node.removeClass('dimmed').addClass('highlighted');
  node.connectedEdges().removeClass('dimmed').addClass('highlighted');
  node.neighborhood().removeClass('dimmed').addClass('highlighted');
  cy.animate({ fit: { eles: node.closedNeighborhood(), padding: 80 }, duration: 280 });
  renderNode(node);
  renderNeighborhood(node);
  selectedEl = node;
  status('Node: ' + (node.data('qualified_name') || node.id()));
}

function focusEdge(edge) {
  clearHL();
  cy.elements().addClass('dimmed');
  edge.removeClass('dimmed').addClass('highlighted');
  edge.source().removeClass('dimmed').addClass('path-start highlighted');
  edge.target().removeClass('dimmed').addClass('path-end highlighted');
  cy.animate({ fit: { eles: edge.connectedNodes().union(edge), padding: 100 }, duration: 280 });
  renderEdge(edge);
  $('neighborhood').innerHTML = `
    <div class="item">
      <div class="title">Edge context</div>
      <div class="meta">${esc(edge.source().data('qualified_name'))} → ${esc(edge.target().data('qualified_name'))}</div>
    </div>
    <div class="item"><div class="title">Source</div><div class="meta mono">${esc(edge.source().id())}</div></div>
    <div class="item"><div class="title">Target</div><div class="meta mono">${esc(edge.target().id())}</div></div>
  `;
  selectedEl = edge;
  status('Edge: ' + edge.source().data('name') + ' → ' + edge.target().data('name'));
}

// ─── path debugger ────────────────────────────────────────────────────
function pathPick(node) {
  pathPicks.push(node);
  if (pathPicks.length === 1) {
    clearHL();
    node.addClass('path-start highlighted');
    $('path-output').innerHTML = `<div class="item"><div class="title">Start node set</div><div class="meta mono">${esc(node.data('qualified_name') || node.id())}</div></div><div class="small" style="padding:6px 0">Click destination node.</div>`;
    status('Path mode — pick destination');
    return;
  }
  if (pathPicks.length === 2) {
    const [s, e] = pathPicks;
    pathPicks = [];
    clearHL();
    // BFS on directed graph
    const result = cy.elements().bfs({ root: s, directed: true });
    const pathNodes = [];
    let cur = e;
    while (cur && cur.id() !== s.id()) {
      pathNodes.unshift(cur);
      const pred = result.predecessors && result.predecessors.filter
        ? result.predecessors.filter(n => n.isNode() && n.neighborhood('node').has(cur)).first()
        : null;
      if (!pred || pred.length === 0) break;
      cur = pred;
    }
    pathNodes.unshift(s);
    // Highlight path edges
    s.addClass('path-start highlighted');
    e.addClass('path-end highlighted');
    for (let i = 0; i < pathNodes.length - 1; i++) {
      const edgesBetween = pathNodes[i].edgesTo(pathNodes[i+1]);
      edgesBetween.addClass('on-path highlighted');
      pathNodes[i+1].addClass('highlighted');
    }
    cy.animate({ fit: { eles: cy.collection(pathNodes).union(s).union(e), padding: 80 }, duration: 280 });
    // Render step list
    const steps = pathNodes.map((n, idx) => `
      <div class="item">
        <div class="title">${idx === 0 ? '🟢 Start' : idx === pathNodes.length-1 ? '🔴 End' : `Step ${idx}`}</div>
        <div class="meta mono">${esc(n.data('qualified_name') || n.id())}</div>
        ${idx < pathNodes.length - 1 ? `<div class="meta">→ calls at line ${esc(n.edgesTo(pathNodes[idx+1]).first().data('call_line'))}</div>` : ''}
      </div>`).join('');
    $('path-output').innerHTML = steps || `<div class="small">No direct path found between these nodes.</div>`;
    status('Path rendered — ' + pathNodes.length + ' hops');
  }
}

// ─── cy event listeners ───────────────────────────────────────────────
cy.on('tap', 'node', evt => {
  if (pathMode) { pathPick(evt.target); return; }
  focusNode(evt.target);
});
cy.on('tap', 'edge', evt => {
  if (pathMode) return;
  focusEdge(evt.target);
});
cy.on('tap', evt => {
  if (evt.target !== cy) return;
  clearHL();
  $('inspector').innerHTML = '';
  $('neighborhood').innerHTML = '';
  $('empty-hint').style.display = 'block';
  selectedEl = null;
  status('Ready');
});

// ─── controls ────────────────────────────────────────────────────────
function applyFilter() {
  const q  = $('search').value.trim().toLowerCase();
  const ft = $('filter-type').value;
  cy.nodes().forEach(n => {
    const d = n.data();
    const blob = [d.id, d.name, d.qualified_name, d.source_path || '', d.class_name || '', d.language || ''].join(' ').toLowerCase();
    let show = !q || blob.includes(q);
    if (ft === 'code')     show = show && d.source_type === 'code';
    if (ft === 'external') show = show && d.source_type === 'external';
    if (ft === 'method')   show = show && !!d.is_method;
    if (ft === 'function') show = show && !d.is_method && d.source_type === 'code';
    n.style('display', show ? 'element' : 'none');
  });
  cy.edges().forEach(e => {
    const v = e.source().style('display') !== 'none' && e.target().style('display') !== 'none';
    e.style('display', v ? 'element' : 'none');
  });
  status('Filter applied');
}

function doLayout() {
  const name = $('layout').value;
  const opts = { name, animate: true, fit: true, padding: 60 };
  if (name === 'dagre') Object.assign(opts, { rankDir:'LR', nodeSep:50, rankSep:100, edgeSep:10 });
  if (name === 'cose')  Object.assign(opts, { idealEdgeLength:120, nodeRepulsion:5000, animate:true });
  if (name === 'concentric') Object.assign(opts, { minNodeSpacing:50, concentric: n => n.degree(), levelWidth: () => 3 });
  cy.layout(opts).run();
  status('Layout: ' + name);
}

function renderNodeBrowser() {
  const sorted = [...cy.nodes()].sort((a,b) =>
    (a.data('qualified_name')||'').localeCompare(b.data('qualified_name')||''));
  $('node-browser').innerHTML = sorted.map(n => `
    <div class="node-chip" data-nid="${esc(n.id())}">
      <div class="cn">${esc(n.data('name'))}</div>
      <div class="cs mono">${esc(n.data('qualified_name') || n.id())}</div>
    </div>`).join('');
  $('node-browser').querySelectorAll('.node-chip').forEach(el =>
    el.addEventListener('click', () => {
      const n = cy.getElementById(el.dataset.nid);
      if (n) focusNode(n);
    })
  );
}

$('search').addEventListener('input', applyFilter);
$('filter-type').addEventListener('change', applyFilter);
$('btn-layout').addEventListener('click', doLayout);
$('btn-fit').addEventListener('click', () => cy.fit(cy.elements(':visible'), 60));
$('btn-reset').addEventListener('click', () => {
  $('search').value = '';
  $('filter-type').value = 'all';
  cy.elements().style('display','element');
  clearHL();
  cy.fit(cy.elements(), 60);
  status('Reset');
});
$('btn-labels').addEventListener('click', () => {
  labelsOn = !labelsOn;
  cy.nodes().toggleClass('hide-label', !labelsOn);
  status('Labels: ' + (labelsOn ? 'ON' : 'OFF'));
});
$('btn-edgelabels').addEventListener('click', () => {
  edgeLabels = !edgeLabels;
  cy.edges().toggleClass('edge-label', edgeLabels);
  status('Edge labels: ' + (edgeLabels ? 'ON' : 'OFF'));
});
$('btn-isolated').addEventListener('click', () => {
  clearHL();
  const iso = cy.nodes().filter(n => n.connectedEdges().length === 0);
  cy.elements().addClass('dimmed');
  iso.removeClass('dimmed').addClass('isolated highlighted');
  if (iso.length) cy.animate({ fit: { eles: iso, padding: 80 }, duration: 280 });
  status('Isolated: ' + iso.length);
});
$('btn-hotspots').addEventListener('click', () => {
  clearHL();
  const hot = cy.nodes().filter(n => (n.indegree() + n.outdegree()) >= 3);
  cy.elements().addClass('dimmed');
  hot.removeClass('dimmed').addClass('highlighted');
  hot.connectedEdges().removeClass('dimmed').addClass('highlighted');
  if (hot.length) cy.animate({ fit: { eles: hot.union(hot.connectedEdges()), padding: 80 }, duration: 280 });
  status('Hotspots: ' + hot.length);
});
$('btn-pathmode').addEventListener('click', () => {
  pathMode = !pathMode;
  pathPicks = [];
  $('btn-pathmode').textContent = pathMode ? 'Disable Path Mode' : 'Path Mode';
  $('path-section').classList.toggle('visible', pathMode);
  if (pathMode) { $('path-output').innerHTML = '<div class="small">Click start node, then end node.</div>'; }
  status(pathMode ? 'Path Mode ON — pick start node' : 'Path Mode OFF');
});
$('btn-clear').addEventListener('click', () => {
  clearHL();
  selectedEl = null; pathPicks = [];
  $('inspector').innerHTML = '';
  $('neighborhood').innerHTML = '';
  $('empty-hint').style.display = 'block';
  status('Cleared');
});
$('btn-zoomin').addEventListener('click',  () => cy.zoom({ level: cy.zoom()*1.25, renderedPosition:{ x:cy.width()/2, y:cy.height()/2 } }));
$('btn-zoomout').addEventListener('click', () => cy.zoom({ level: cy.zoom()*0.8,  renderedPosition:{ x:cy.width()/2, y:cy.height()/2 } }));
$('btn-center').addEventListener('click',  () => { if (selectedEl) cy.center(selectedEl); });

// ─── boot ─────────────────────────────────────────────────────────────
updateStats();
renderNodeBrowser();
status('Graph loaded — ' + graphData.nodes.length + ' nodes, ' + graphData.edges.length + ' edges');
</script>
</body>
</html>""".replace("%CYTOSCAPE%", _CYTOSCAPE_CDN)
    .replace("%DAGRE%", _DAGRE_CDN)
    .replace("%CYDAGRE%", _CY_DAGRE_CDN)
)
