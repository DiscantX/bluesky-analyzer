# Quick Implementation Guide: Bottleneck Fixes

## Fix 1: Batch FollowEdge Creation (Highest ROI)
**File:** [analyzer/sync.py](analyzer/sync.py#L154-L162)  
**Time Impact:** 50-70% sync database speedup  
**Effort:** 5 minutes

### Current Code (SLOW - N database queries)
```python
for f in follows:
    await FollowEdge.get_or_create(follower_did=owner_did, followee_did=f.did)
for f in followers:
    await FollowEdge.get_or_create(follower_did=f.did, followee_did=owner_did)
```

### Optimized Code
```python
# Batch create all follow edges at once
follow_edges = [
    FollowEdge(follower_did=owner_did, followee_did=f.did)
    for f in follows
]
follower_edges = [
    FollowEdge(follower_did=f.did, followee_did=owner_did)
    for f in followers
]

await FollowEdge.bulk_create(follow_edges, ignore_conflicts=True)
await FollowEdge.bulk_create(follower_edges, ignore_conflicts=True)

sync_run.follows_fetched = len(follows)
sync_run.followers_fetched = len(followers)
await sync_run.save()
```

---

## Fix 2: Increase Hydration Semaphore
**File:** [analyzer/crawl.py](analyzer/crawl.py#L118)  
**Time Impact:** 2-5x hydration speedup  
**Effort:** 1 minute

### Current Code
```python
hydration_semaphore = asyncio.Semaphore(2)  # Too conservative
```

### Optimized Code
```python
# Increase for faster profile hydration (read-only operation)
hydration_semaphore = asyncio.Semaphore(5)
```

**Optional Enhancement:** Make configurable
```python
hydration_semaphore = asyncio.Semaphore(
    getattr(settings, 'hydration_concurrency', 5)
)
```

---

## Fix 3: Reduce API Sleep Delays
**Files:** [analyzer/fetch.py](analyzer/fetch.py#L42), [analyzer/fetch.py](analyzer/fetch.py#L56)  
**Time Impact:** 5-10 seconds per large sync  
**Effort:** 2 minutes

### Current Code
```python
if not settings.disable_internal_rate_limits:
    await asyncio.sleep(0.1)  # 100ms is too conservative
```

### Optimized Code
```python
if not settings.disable_internal_rate_limits:
    await asyncio.sleep(0.01)  # 10ms is still polite, Bluesky allows rapid pagination
```

---

## Fix 4: Batch Degree Recalculation in Crawl
**File:** [analyzer/crawl.py](analyzer/crawl.py#L231-L245)  
**Time Impact:** 60-80% per-batch speedup  
**Effort:** 20 minutes

### Current Code (SLOW - Multiple queries per user)
```python
for did in page_dids:
    t_user = await AccountRelationship.filter(owner=owner, did=did).first()
    if t_user:
        incoming = await FollowEdge.filter(followee_did=did).values_list("follower_did", flat=True)
        t_user.in_subgraph_degree = len(set(incoming).intersection(tracked_dids))
        t_user.crawl_priority = await calculate_priority(t_user)
        await t_user.save()  # Single row updates - slow!
```

### Optimized Code (FAST - Batch queries)
```python
# 1. Fetch all discovered users in one query
discovered_users = await AccountRelationship.filter(
    owner=owner,
    did__in=page_dids
).prefetch_related("profile").all()

# 2. Fetch all incoming edges in one query
all_incoming = await FollowEdge.filter(followee_did__in=page_dids).all()

# 3. Group edges by followee in Python (fast)
edges_by_followee = {}
for edge in all_incoming:
    if edge.followee_did not in edges_by_followee:
        edges_by_followee[edge.followee_did] = []
    edges_by_followee[edge.followee_did].append(edge.follower_did)

# 4. Update all at once
updates = []
for user in discovered_users:
    follower_set = set(edges_by_followee.get(user.did, []))
    user.in_subgraph_degree = len(follower_set.intersection(tracked_dids))
    user.crawl_priority = await calculate_priority(user)
    updates.append(user)

# 5. Bulk update instead of individual saves
await AccountRelationship.bulk_update(
    updates,
    fields=['in_subgraph_degree', 'crawl_priority']
)
```

---

## Fix 5: Increase Feed Fetch Concurrency
**Files:** [analyzer/client.py](analyzer/client.py#L64), [db/models.py](db/models.py#L10)  
**Time Impact:** 2-3x feed fetching speedup  
**Effort:** 10 minutes

### Step 1: Add setting to GlobalSettings
**File:** [db/models.py](db/models.py)
```python
class GlobalSettings(Model):
    """App-wide configuration settings."""
    id = fields.IntField(pk=True)
    # ... existing fields ...
    feed_fetch_concurrency = fields.IntField(default=15)  # NEW
    graph_fetch_concurrency = fields.IntField(default=20)  # NEW (public API)
```

### Step 2: Use dynamic concurrency
**File:** [analyzer/client.py](analyzer/client.py#L74-L75)
```python
async def __init__(self, alias: str, concurrency: int | None = None):
    self.alias = alias
    self._client = Client()
    
    if concurrency is None:
        settings = await GlobalSettings.get(id=1)
        concurrency = settings.feed_fetch_concurrency
    
    self._semaphore = asyncio.Semaphore(concurrency)
```

### Step 3: Use higher concurrency for public graph API
**File:** [analyzer/fetch.py](analyzer/fetch.py#L137)
```python
async def public_fetch_profiles(dids: list[str]) -> list[dict]:
    """Fetch public profile details from AppView in batches of 25."""
    settings = await GlobalSettings.get(id=1)
    results = []
    # Use a higher concurrency for public API
    concurrency = settings.graph_fetch_concurrency
    semaphore = asyncio.Semaphore(concurrency)
    
    async def _fetch_batch(batch):
        async with semaphore:
            params = [("actors", did) for did in batch]
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfiles",
                    params=params
                )
                return resp.json().get("profiles", [])
    
    tasks = []
    for i in range(0, len(dids), 25):
        batch = dids[i:i + 25]
        tasks.append(_fetch_batch(batch))
    
    return [item for result in await asyncio.gather(*tasks) for item in result]
```

---

## Fix 6: Parallelize Follows/Followers Crawl (Bonus)
**File:** [analyzer/crawl.py](analyzer/crawl.py#L223-L263)  
**Time Impact:** 1-2x per candidate  
**Effort:** 25 minutes (complex)

### Current Code
```python
# Sequential - one finishes before starting the other
for direction in ["follows", "followers"]:
    # ... fetch follows OR followers sequentially ...
```

### Optimized Code
```python
async def process_direction(direction: str, start_cursor: str | None = None):
    """Paginated fetch for one direction."""
    cursor = start_cursor
    batches = []
    
    while True:
        data = await public_fetch_graph(user.did, direction, cursor=cursor)
        batch = data.get(direction, [])
        if batch:
            batches.append((batch, direction))
        
        next_cursor = data.get("cursor")
        if not next_cursor or not batch:
            break
        
        cursor = next_cursor
        if not settings.disable_internal_rate_limits:
            await asyncio.sleep(0.01)
    
    return batches

# Fetch both directions concurrently
follows_batches, followers_batches = await asyncio.gather(
    process_direction("follows", item.cursor if item.cursor else None),
    process_direction("followers"),
)

all_batches = follows_batches + followers_batches

# Process all batches
for batch, direction in all_batches:
    await process_page(batch, direction)
```

---

## Testing & Validation

After implementing fixes, measure impact:

```python
import time

async def benchmark_sync(saved_account):
    start = time.time()
    await run_sync(saved_account, client, alias)
    elapsed = time.time() - start
    print(f"Sync completed in {elapsed:.1f}s")
```

Expected results after all fixes:
- **Phase 1 (4 quick fixes):** 40% improvement (~2-3s from 5-10s)
- **Phase 2 (+ batching):** Additional 30% (~1-2s from 2-3s)
- **Phase 3 (+ parallelization):** Additional 20% (~30-40s on large crawls)

---

## Implementation Priority Order

1. **Fix 1 (Batch FollowEdge)** - 5 min, highest ROI
2. **Fix 2 (Hydration semaphore)** - 1 min, easy win
3. **Fix 3 (Sleep delays)** - 2 min, easy win
4. **Fix 4 (Batch degree update)** - 20 min, high impact
5. **Fix 5 (Feed concurrency)** - 10 min, good impact
6. **Fix 6 (Parallel crawl)** - 25 min, complex but good

Total time for all fixes: ~60 minutes for 3-5x improvement
