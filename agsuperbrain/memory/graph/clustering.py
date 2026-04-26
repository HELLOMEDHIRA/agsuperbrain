"""
clustering.py — Community detection via Leiden algorithm.

Uses graspologic (network analysis) for Leiden community detection.
Clusters graph by edge density — no embeddings needed.

Leiden finds high-quality communities that are:
  - Internally dense
  - Sparse between communities
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

if TYPE_CHECKING:
    from agsuperbrain.memory.graph.graph_store import GraphStore

_clusterer_cache: LeidenClusterer | None = None


def _export_graph_to_nx(gs: GraphStore) -> nx.Graph:
    """Export KùzuDB subgraph to NetworkX for clustering."""
    G = nx.Graph()

    rows = gs.query("MATCH (a)-[r:CALLS]->(b) RETURN a.id, b.id, r.call_line")
    for src, dst, _ in rows:
        if src and dst:
            G.add_edge(src, dst)

    return G


@dataclass
class Community:
    id: int
    nodes: list[str]
    name: str = ""
    size: int = 0

    def __post_init__(self):
        self.size = len(self.nodes)
        if not self.name:
            self.name = f"community_{self.id}"


@dataclass
class ClusteringResult:
    communities: list[Community]
    modularity: float
    node_to_community: dict[str, int]


def _compute_modularity(G: nx.Graph, partition: dict[str, int]) -> float:
    """Compute modularity given a graph and partition."""
    if not G.number_of_edges():
        return 0.0

    m = G.number_of_edges()
    degrees = dict(G.degree())

    Q = 0.0
    for u, v in G.edges():
        if u not in partition or v not in partition:
            continue
        if partition[u] == partition[v]:
            du = degrees.get(u, 0)
            dv = degrees.get(v, 0)
            Q += 1 - (du * dv) / (2 * m)

    return Q / (2 * m)


class LeidenClusterer:
    """
    Leiden community detection — graph-topology based.

    No embeddings needed — uses edge density directly.
    Algorithm: Louvain → Refinement → Contraction → Modularization
    """

    def __init__(
        self,
        resolution: float = 1.0,
        random_state: int = 42,
    ) -> None:
        self.resolution = resolution
        self.random_state = random_state

    def fit_predict(
        self,
        graph_store,
    ) -> ClusteringResult:
        """
        Detect communities in a GraphStore.

        Returns:
            ClusteringResult with communities + modularity score.
        """
        from graspologic.partition import leiden

        G = _export_graph_to_nx(graph_store)
        if G.number_of_nodes() == 0:
            return ClusteringResult(
                communities=[],
                modularity=0.0,
                node_to_community={},
            )

        partition = leiden(
            G,
            resolutions=self.resolution,
            random_state=self.random_state,
        )

        community_nodes: dict[int, list[str]] = defaultdict(list)
        node_to_community = {}
        for node, comm_id in partition.items():
            community_nodes[comm_id].append(node)
            node_to_community[node] = comm_id

        communities = [Community(id=cid, nodes=nodes) for cid, nodes in sorted(community_nodes.items())]

        modularity = _compute_modularity(G, partition)

        return ClusteringResult(
            communities=communities,
            modularity=modularity,
            node_to_community=node_to_community,
        )


def cluster(
    graph_store,
    resolution: float = 1.0,
    random_state: int = 42,
) -> ClusteringResult:
    """
    Convenience function for community detection.

    Usage:
        result = cluster(graph_store)
        for comm in result.communities:
            print(f"Community {comm.id}: {comm.size} nodes")
    """
    clusterer = LeidenClusterer(
        resolution=resolution,
        random_state=random_state,
    )
    return clusterer.fit_predict(graph_store)


def get_clusterer() -> LeidenClusterer:
    """Get cached LeidenClusterer instance."""
    global _clusterer_cache
    if _clusterer_cache is None:
        _clusterer_cache = LeidenClusterer()
    return _clusterer_cache
