# Project: Community NLP & Human-Readable Identity

## Objective
Transform community naming and descriptions from raw keyword clusters (e.g., "Hotel & Entrepreneur & Click") into human-readable, grammatically correct sentences that accurately classify the group's purpose.

## Core Challenges
1. **Noise Removal:** Current TF-IDF includes generic words like "Click," "Full," and "Room."
2. **Language Awareness:** Non-English communities often contain stop-words (e.g., "one", "two" in other languages) that aren't filtered.
3. **Readability:** Lack of sentence structure makes the identity feel "robotic."

## Proposed Solutions (No-Paid AI)

### 1. POS-Tagging & Phrase Extraction (spaCy/NLTK)
- **Noun-Only Names:** Use a local spaCy model to filter top keywords. Only Nouns (NOUN) and Proper Nouns (PROPN) should be allowed in the Community Name.
- **Phrase Mining:** Implement Bigram/Trigram detection so "Software Development" is captured as one entity instead of "Software" and "Development" separately.

### 2. Multi-Language Intelligence
- **Language Detection:** Use `py3langid` or `fasttext-langid` to detect the dominant language of a community's top 100 bios.
- **Dynamic Stopwords:** Load language-specific stop-word lists based on the detection result to filter out common noise like "y", "le", "da", etc.

### 3. Template-Based Natural Language Generation (NLG)
- Replace string-joining with a logic-driven template engine.
- **Logic:**
    - If `avg_clustering` > 0.4: "A tight-knit circle..."
    - If `size` > 10% of network: "A major hub..."
    - **Template:** "This [Density] [Language] community is primarily centered around **[Topic A]** and **[Topic B]**, acting as a hub for **[Topic C]**. Key influence stems from **[@User1]** and **[@User2]**."

## Implementation Roadmap
1. **Refactor `generate_community_summaries`:** Move away from pure TF-IDF.
2. **Integrate spaCy:** Use the `en_core_web_sm` (and equivalents for other languages) for POS filtering.
3. **Dictionary Filtering:** Create a "Profile Noise" dictionary for words like "Link", "Bio", "Social" that TF-IDF often captures but humans find useless.
```

---

### Project 2: Graph Resolution & Visual Structure
**File Path:** `c:\Users\Admin\Documents\Dylan\APE\bluesky-analyzer\docs\project_graph_resolution.md`

```diff
# Project: Graph Resolution & Visual Structure

## Objective
Solve the "Black Blob" problem in the visualization and increase the granularity of community detection to allow for more than 25-30 groups.

## Core Challenges
1. **Algorithm Bias:** The Louvain algorithm naturally seeks to maximize modularity, which often merges smaller niches into large generic blobs.
2. **Disconnected Meta-Nodes:** The Community Overview lacks edges between communities, causing them to float as unrelated circles.
3. **Visual Density:** Too many overlapping edges in Macro-view create a "hairball" effect.

## Proposed Solutions

### 1. The Resolution Parameter (Louvain Tuning)
- **Granularity Control:** Update `nx.community.louvain_communities` to use the `resolution` parameter.
- **Logic:** Increasing resolution (e.g., from 1.0 to 2.5) forces the algorithm to find smaller, more cohesive sub-communities, effectively breaking the 30-community cap.

### 2. Inter-Community Edge Calculation
- **Bridge Discovery:** Calculate the total number of followers between "Community A" and "Community B."
- **Meta-Graph Edges:** Render edges between community meta-nodes in the "Community Overview" weighted by this inter-community flow. This shows which communities are neighbors and which are isolated.

### 3. Visual Separation (Convex Hulls & Gravity)
- **Community Hulls:** In D3, implement "Convex Hulls" (semi-transparent shaded areas) that wrap around all nodes in a community. This provides a "map-like" feel (islands/continents).
- **Community Gravity:** Modify the force simulation to include a "Community Center" force. Nodes are attracted to their own community's centroid and repelled by other communities, forcing the blobs to separate spatially.

## Implementation Roadmap
1. **Settings Update:** Add `louvain_resolution` to the `GlobalSettings` model and UI.
2. **Backend Update (`metrics.py`):** Implement the weighted inter-community edge calculation during the graph analysis phase.
3. **Frontend Update (`graph.js`):** 
    - Implement D3 Convex Hulls for visual grouping.
    - Add force-simulation adjustments to push community clusters apart.
    - Render weighted links between Meta-Nodes in Community Overview.
```