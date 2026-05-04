"""
analyzer/metrics.py
Computes network graph metrics (FlowRank, Community detection) using NetworkX.
"""

import logging
import asyncio
import networkx as nx
from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_python
from typing import Dict, Any
from tortoise import connections
from db.models import AccountRelationship, FollowEdge, SavedAccount

logger = logging.getLogger(__name__)
SQLITE_IN_CHUNK = 400
CLUSTERING_TOP_N = 1000
FULL_LOUVAIN_MAX_NODES = 10000


def _chunks(values: list[str], size: int = SQLITE_IN_CHUNK):
    for i in range(0, len(values), size):
        yield values[i:i + size]

async def run_graph_analysis(owner: SavedAccount):
    """
    Orchestrates the graph metric computation for a specific account.
    Loads edges, builds a NetworkX graph, computes metrics, and persists them.
    """
    logger.info(f"Starting graph analysis for {owner.handle}...")
    
    # 1. Get all nodes in the local universe for this owner
    relationships = await AccountRelationship.filter(owner=owner).all()
    tracked_dids = {rel.did for rel in relationships}
    
    # Include the owner in the graph nodes so we can use the edges connected to them
    graph_nodes = tracked_dids | {owner.did}
    
    if not graph_nodes:
        logger.warning("No tracked users to analyze.")
        return

    # 3. Build graph
    G = nx.DiGraph()
    G.add_nodes_from(tracked_dids)
    graph_node_list = list(graph_nodes)
    edge_count = 0
    for did_batch in _chunks(graph_node_list):
        edges = await FollowEdge.filter(follower_did__in=did_batch).all()
        for edge in edges:
            if edge.followee_did in graph_nodes:
                G.add_edge(edge.follower_did, edge.followee_did)
                edge_count += 1

    if G.number_of_nodes() == 0:
        return

    # 4. Compute metrics in a thread pool to avoid blocking the event loop
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, _compute_metrics_sync, G)

    # 5. Persist back to DB. Use executemany because saving tens of thousands
    # of rows one-by-one makes sync shutdown and Ctrl+C feel wedged.
    updates = []
    for rel in relationships:
        metrics = results.get(rel.did)
        if metrics:
            updates.append((
                metrics.get("flowrank"),
                metrics.get("community"),
                metrics.get("in_degree", 0),
                metrics.get("clustering"),
                rel.id,
            ))

    if updates:
        conn = connections.get("default")
        for batch in _chunks(updates, SQLITE_IN_CHUNK):
            await conn.execute_many(
                """
                UPDATE account_relationships
                SET flowrank_score = ?,
                    community_id = ?,
                    in_subgraph_degree = ?,
                    clustering_coefficient = ?
                WHERE id = ?
                """,
                batch,
            )

    logger.info(f"Graph analysis complete for {owner.handle}. Nodes: {G.number_of_nodes()}, Edges: {edge_count}")


def _compute_metrics_sync(G: nx.DiGraph) -> Dict[str, Dict[str, Any]]:
    """Synchronous NetworkX logic running in a thread pool."""
    # FlowRank (PageRank)
    try:
        # alpha=0.85 is standard; weight=None because we treat all follows equally
        pr = nx.pagerank(G, alpha=0.85)
    except Exception as e:
        logger.warning(f"FlowRank fast computation failed, using pure-Python fallback: {e}")
        try:
            pr = _pagerank_python(G, alpha=0.85)
        except Exception as fallback_error:
            logger.error(f"FlowRank computation failed: {fallback_error}")
            pr = {}

    undirected = G.to_undirected()

    # Community Detection. Louvain is useful but expensive; for larger graphs,
    # connected components are a fast coarse fallback until metrics are moved
    # into an incremental/background job.
    try:
        if G.number_of_nodes() <= FULL_LOUVAIN_MAX_NODES:
            communities = nx.community.louvain_communities(undirected, seed=42)
        else:
            communities = nx.connected_components(undirected)
        community_map = {}
        for i, community_nodes in enumerate(communities):
            for did in community_nodes:
                community_map[did] = i
    except Exception as e:
        logger.error(f"Community detection failed: {e}")
        community_map = {}

    # Clustering coefficient is expensive for all nodes. Compute it for the
    # highest-FlowRank nodes only, matching PROJECT.md's planned top-N approach.
    clustering = {}
    try:
        top_nodes = [
            node
            for node, _ in sorted(pr.items(), key=lambda item: item[1], reverse=True)[:CLUSTERING_TOP_N]
        ]
        clustering = nx.clustering(undirected, nodes=top_nodes)
    except Exception as e:
        logger.error(f"Clustering computation failed: {e}")
    
    # Prepare results map
    return {
        node: {
            "flowrank": pr.get(node),
            "community": community_map.get(node),
            "in_degree": G.in_degree(node),
            "clustering": clustering.get(node)
        }
        for node in G.nodes()
    }
