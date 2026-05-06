"""
analyzer/metrics.py
Computes network graph metrics (FlowRank, Community detection) using NetworkX.
"""

import logging
import asyncio
import json
import math
from collections import Counter
import networkx as nx
from datetime import datetime, timezone, timedelta
from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_python
from typing import Dict, Any
from tortoise import connections, transactions
from db.models import AccountRelationship, FollowEdge, SavedAccount, CommunityMetadata, GlobalSettings, Profile
from analyzer.client import get_client
from analyzer.analyze import build_tracked_user_data, STOP_WORDS
from sklearn.feature_extraction.text import TfidfVectorizer
from analyzer.fetch import fetch_feeds_concurrent, fetch_all_follows, fetch_all_followers

logger = logging.getLogger(__name__)
SQLITE_IN_CHUNK = 32766  # SQLite parameter limit (SQLITE_MAX_VARIABLE_NUMBER) is 32,766
CLUSTERING_TOP_N = 1000
FULL_LOUVAIN_MAX_NODES = 10000


def _chunks(values: list[str], size: int = SQLITE_IN_CHUNK):
    for i in range(0, len(values), size):
        yield values[i:i + size]

async def run_graph_analysis(owner: SavedAccount, on_progress=None):
    """
    Orchestrates the graph metric computation for a specific account.
    Loads edges, builds a NetworkX graph, computes metrics, and persists them.
    """
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
    G.add_nodes_from(graph_nodes)
    graph_node_list = list(graph_nodes)
    total_nodes = len(graph_node_list)
    nodes_processed = 0
    edge_count = 0
    for did_batch in _chunks(graph_node_list):
        # Optimization: use values_list to avoid expensive ORM object instantiation
        edges = await FollowEdge.filter(follower_did__in=did_batch).values_list("follower_did", "followee_did")
        for f_did, t_did in edges:
            if t_did in graph_nodes:
                G.add_edge(f_did, t_did)
                edge_count += 1
        nodes_processed += len(did_batch)
        if on_progress:
            pct = 5 + int((nodes_processed / total_nodes) * 15)
            await on_progress(f"Building social graph ({nodes_processed}/{total_nodes} nodes)...", pct)

    if G.number_of_nodes() == 0:
        return

    settings = await GlobalSettings.get(id=1)

    # 4. Compute metrics in a thread pool to avoid blocking the event loop
    loop = asyncio.get_running_loop()

    if on_progress:
        await on_progress(f"Computing FlowRank ({G.number_of_nodes()} nodes)...", 20)
    pr = await loop.run_in_executor(None, _compute_pagerank, G)

    if on_progress:
        await on_progress(f"Detecting communities ({G.number_of_nodes()} nodes)...", 30)
    undirected = await loop.run_in_executor(None, G.to_undirected)
    communities = await loop.run_in_executor(None, _compute_communities, undirected, settings.louvain_resolution, G.number_of_nodes())
    
    community_map = {}
    for i, community_nodes in enumerate(communities):
        for did in community_nodes:
            community_map[did] = i

    if on_progress:
        await on_progress(f"Computing clustering (top {CLUSTERING_TOP_N})...", 40)
    clustering = await loop.run_in_executor(None, _compute_clustering, undirected, pr)

    # 5. Persist back to DB. Use executemany because saving tens of thousands
    # of rows one-by-one makes sync shutdown and Ctrl+C feel wedged.
    updates = []
    for rel in relationships:
        updates.append((
            pr.get(rel.did),
            community_map.get(rel.did),
            G.in_degree(rel.did),
            clustering.get(rel.did),
            rel.id,
        ))

    if on_progress:
        await on_progress("Persisting results...", 50)

    total_updates = len(updates)
    updates_processed = 0
    if updates:
        # Optimization: wrap in a transaction to perform a single commit for all chunks
        async with transactions.in_transaction("default") as conn:
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
                updates_processed += len(batch)
                if on_progress:
                    pct = 50 + int((updates_processed / total_updates) * 20)
                    await on_progress(f"Persisting results ({updates_processed}/{total_updates})...", pct)

    # NEW STEP: Ensure top keywords are populated for key community members
    await _ensure_community_keywords(owner, on_progress=on_progress)

    # 6. Generate Community Metadata
    if on_progress:
        await on_progress("Generating community summaries...", 90)
    await generate_community_summaries(owner)

    if on_progress:
        await on_progress("Graph analysis complete.", 100)
    logger.info(f"Graph analysis complete for {owner.handle}. Nodes: {G.number_of_nodes()}, Edges: {edge_count}")

async def generate_community_summaries(owner: SavedAccount, on_progress=None):
    """Aggregate top keywords and generate names for detected communities."""
    conn = connections.get("default")
    
    # Fetch top 100 members by FlowRank for each community to define its identity
    community_data = await conn.execute_query_dict(
        """
        WITH RankedMembers AS (
            SELECT 
                r.community_id, p.handle, p.top_keywords, r.flowrank_score, r.clustering_coefficient,
                ROW_NUMBER() OVER (PARTITION BY r.community_id ORDER BY r.flowrank_score DESC) as rn
            FROM account_relationships r
            JOIN profiles p ON p.id = r.profile_id
            WHERE r.owner_id = ? AND r.community_id IS NOT NULL
        )
        SELECT community_id, handle, top_keywords, flowrank_score, clustering_coefficient
        FROM RankedMembers
        WHERE rn <= 100
        ORDER BY community_id, flowrank_score DESC
        """,
        [owner.id]
    )
    
    communities = {}
    for row in community_data:
        cid = row["community_id"]
        if cid not in communities:
            communities[cid] = {
                "keywords": Counter(),
                "members": [],
                "avg_cc": []
            }
        
        if len(communities[cid]["members"]) < 5:
            communities[cid]["members"].append(f"@{row['handle']}")
            
        if row["top_keywords"]:
            try:
                kws = json.loads(row["top_keywords"]) if isinstance(row["top_keywords"], str) else row["top_keywords"]
                # Filter out stop words that might have been captured by older logic
                filtered_kws = {k: v for k, v in kws.items() if k.lower() not in STOP_WORDS}
                communities[cid]["keywords"].update(filtered_kws)
            except: pass
        
        if row["clustering_coefficient"]:
            communities[cid]["avg_cc"].append(row["clustering_coefficient"])
            
    # Prepare documents for TfidfVectorizer
    community_ids = sorted(communities.keys())
    community_docs = []
    for cid in community_ids:
        # Create a "document" string by repeating each keyword by its count
        doc = " ".join([word for word, count in communities[cid]["keywords"].items() for _ in range(count)])
        community_docs.append(doc)

    if not community_docs:
        logger.info("No community documents to analyze for TF-IDF.")
        return

    # Initialize TfidfVectorizer with our custom stop words
    # We can also add min_df and max_df to filter very rare or very common words
    vectorizer = TfidfVectorizer(stop_words=list(STOP_WORDS), min_df=1, max_df=0.85)
    
    # Fit and transform the documents
    tfidf_matrix = vectorizer.fit_transform(community_docs)
    feature_names = vectorizer.get_feature_names_out()

    for i, cid in enumerate(community_ids):
        data = communities[cid]
        
        # Get TF-IDF scores for this community
        tfidf_scores = tfidf_matrix[i].toarray().flatten()
        
        # Map feature names to their TF-IDF scores
        word_scores = {feature_names[j]: tfidf_scores[j] for j in tfidf_scores.nonzero()[0]}
        
        # Sort by score to get top keywords
        top_kws_scored = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)[:5] # Get top 5 for better selection
        
        # Filter keywords that have a significant TF-IDF score to avoid noise
        # A threshold of 0.1 is a common starting point, can be tuned
        significant_kws = [k[0] for k in top_kws_scored if k[1] > 0.1]
        
        name = " & ".join([k.capitalize() for k in significant_kws]) if significant_kws else f"Community {cid}"
        
        # Ensure description uses the significant keywords
        description_kws = ", ".join(significant_kws) if significant_kws else f"Community {cid}"
        # Determine structure description
        avg_cc = sum(data["avg_cc"]) / len(data["avg_cc"]) if data["avg_cc"] else 0
        structure = "Tight-knit" if avg_cc > 0.3 else "Broad"
        
        description = ( # Corrected to use significant_kws
            f"A {structure.lower()} group focused on {description_kws}. "
            f"Primary influencers include {', '.join(data['members'])}."
        )

        await CommunityMetadata.update_or_create(
            owner=owner,
            community_id=cid,
            defaults={
                "name": f"{structure} {name}",
                "description": description,
                "top_keywords": dict(data["keywords"].most_common(10)),
                "representative_members": data["members"]
            }
        )

async def _ensure_community_keywords(owner: SavedAccount, top_n_per_community: int = 100, on_progress=None):
    """
    Identifies top N members per community and ensures their top_keywords are populated.
    If keywords are missing or stale, their feeds are re-analyzed.
    """
    logger.info(f"Ensuring top keywords for key community members for {owner.handle}...")
    conn = connections.get("default")
    settings = await GlobalSettings.get(id=1)
    
    # Fetch top N members by FlowRank for each community
    # Also get their current top_keywords and last_analyzed_at
    community_members_query = f"""
        WITH RankedMembers AS (
            SELECT 
                r.did,
                p.id as profile_id,
                p.handle,
                r.community_id,
                r.flowrank_score,
                p.top_keywords,
                p.last_analyzed_at,
                ROW_NUMBER() OVER (PARTITION BY r.community_id ORDER BY r.flowrank_score DESC) as rn
            FROM account_relationships r
            JOIN profiles p ON p.id = r.profile_id
            WHERE r.owner_id = ? AND r.community_id IS NOT NULL
        )
        SELECT did, profile_id, handle, community_id, flowrank_score, top_keywords, last_analyzed_at
        FROM RankedMembers
        WHERE rn <= {top_n_per_community}
    """
    top_members = await conn.execute_query_dict(community_members_query, [owner.id])

    dids_to_reanalyze = []
    profiles_to_reanalyze = {} # Store profile objects to pass to build_tracked_user_data
    did_to_community = {} # Map DIDs to community IDs for accurate logging


    # Determine which profiles need re-analysis
    now = datetime.now(timezone.utc)
    # Use a fixed staleness for keywords, e.g., 30 days, or if keywords are missing
    KEYWORD_STALENESS_THRESHOLD = timedelta(days=30) 

    for member in top_members:
        did = member["did"]
        profile_id = member["profile_id"]
        last_analyzed_at = member["last_analyzed_at"]
        top_keywords = member["top_keywords"]
        did_to_community[did] = member["community_id"]

        needs_reanalysis = False
        if not top_keywords: # Keywords are missing
            needs_reanalysis = True
        elif last_analyzed_at:
            # last_analyzed_at from DB is a string, convert to datetime
            dt_last_analyzed = datetime.fromisoformat(last_analyzed_at.replace("Z", "+00:00")) if isinstance(last_analyzed_at, str) else last_analyzed_at
            if (now - dt_last_analyzed) > KEYWORD_STALENESS_THRESHOLD:
                needs_reanalysis = True
        else: # last_analyzed_at is null but top_keywords might be present (e.g. from manual edit)
            needs_reanalysis = True # If no analysis date, assume stale

        if needs_reanalysis:
            dids_to_reanalyze.append(did)
            profiles_to_reanalyze[did] = await Profile.get(id=profile_id)

    if not dids_to_reanalyze:
        logger.info("No key community members require keyword re-analysis.")
        return

    logger.info(f"Re-analyzing feeds for {len(dids_to_reanalyze)} key community members...")

    total_reanalyze = len(dids_to_reanalyze)
    completed = 0
    updated_profiles = []
    client = await get_client(owner)

    owner_follows_list = await fetch_all_follows(client, owner.handle)
    owner_follows = {p.did for p in owner_follows_list}
    owner_followers_list = await fetch_all_followers(client, owner.handle)
    owner_followers = {p.did for p in owner_followers_list}

    async for did, feed_items in fetch_feeds_concurrent(
        client,
        dids_to_reanalyze,
        limit_per_actor=settings.feed_sample_size,
    ):
        completed += 1
        profile_obj = profiles_to_reanalyze.get(did)
        if not profile_obj:
            logger.warning(f"Profile object not found for DID {did} during keyword re-analysis.")
            continue

        data = build_tracked_user_data(
            profile=profile_obj,
            feed_items=feed_items,
            owner_did=owner.did,
            i_follow_them=did in owner_follows,
            they_follow_me=did in owner_followers,
            inactive_days=settings.inactivity_threshold_days,
            repost_threshold=settings.repost_ratio_threshold,
        )
        data["last_analyzed_at"] = now

        profile_obj.top_keywords = data["top_keywords"]
        profile_obj.last_analyzed_at = data["last_analyzed_at"]
        updated_profiles.append(profile_obj)
        
        if on_progress and completed % 5 == 0:
            pct = 70 + int((completed / total_reanalyze) * 20) # 70% to 90%
            await on_progress(f"Community keywords: {completed}/{total_reanalyze}...", pct)

    if updated_profiles:
        # Perform a single bulk update to save all analyzed profiles at once,
        # dramatically reducing the number of SQLite transactions.
        await Profile.bulk_update(updated_profiles, fields=["top_keywords", "last_analyzed_at"])
        for p in updated_profiles:
            logger.debug(f"Updated keywords for {p.handle} (Community {did_to_community.get(p.did, 'N/A')})")

    logger.info(f"Finished keyword re-analysis for key community members for {owner.handle}.")

def _compute_pagerank(G: nx.DiGraph):
    try:
        return nx.pagerank(G, alpha=0.85)
    except Exception as e:
        logger.warning(f"FlowRank fast computation failed, using pure-Python fallback: {e}")
        try:
            return _pagerank_python(G, alpha=0.85)
        except Exception as fallback_error:
            logger.error(f"FlowRank computation failed: {fallback_error}")
            return {}

def _compute_communities(undirected: nx.Graph, resolution: float, node_count: int):
    try:
        if node_count <= FULL_LOUVAIN_MAX_NODES:
            return nx.community.louvain_communities(undirected, seed=42, resolution=resolution)
        elif node_count <= 500000:
            return nx.community.label_propagation_communities(undirected)
        else:
            return nx.connected_components(undirected)
    except Exception as e:
        logger.error(f"Community detection failed: {e}")
        return []

def _compute_clustering(undirected: nx.Graph, pr: Dict):
    try:
       top_nodes = [
            node
            for node, _ in sorted(pr.items(), key=lambda item: item[1], reverse=True)[:CLUSTERING_TOP_N]
        ]
       return nx.clustering(undirected, nodes=top_nodes)
     
    except Exception as e:
        logger.error(f"Clustering computation failed: {e}")
        return {}
