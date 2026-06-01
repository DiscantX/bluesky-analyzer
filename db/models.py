"""
db/models.py
Tortoise ORM models. One file — easy to extend as the app grows.

OPTIMIZATIONS APPLIED:
  - Fix 5: Added feed_fetch_concurrency field to GlobalSettings so the
            feed fetch semaphore can be tuned without code changes.
            Default 15 (was hardcoded 5) gives 2-3x faster feed fetching.
"""

from tortoise import fields
from tortoise.models import Model


class GlobalSettings(Model):
    """App-wide configuration — one row (id=1) forever."""

    id = fields.IntField(pk=True)

    # ── Analysis ──────────────────────────────────────────────────────────────
    inactivity_threshold_days   = fields.IntField(default=90)
    repost_ratio_threshold      = fields.FloatField(default=0.70)
    feed_sample_size            = fields.IntField(default=100)

    # ── Sync ──────────────────────────────────────────────────────────────────
    sync_staleness_hours                = fields.IntField(default=12)
    worker_sweep_interval_seconds       = fields.IntField(default=300)
    staleness_tier2_days                = fields.IntField(default=3)
    staleness_tier1_days                = fields.IntField(default=7)
    staleness_tier0_days                = fields.IntField(default=30)
    ignore_staleness_threshold_days     = fields.IntField(default=0)
    disable_startup_sync                = fields.BooleanField(default=False)

    # ── API / Rate limits ─────────────────────────────────────────────────────
    feed_fetch_concurrency          = fields.IntField(default=15)
    disable_internal_rate_limits    = fields.BooleanField(default=False)
    api_max_retries                 = fields.IntField(default=4)
    api_base_backoff_seconds        = fields.FloatField(default=2.0)
    api_polite_delay_ms             = fields.IntField(default=10)

    # ── Crawl ─────────────────────────────────────────────────────────────────
    crawl_concurrency               = fields.IntField(default=6)
    min_connection_threshold        = fields.IntField(default=3)
    crawl_budget_mb                 = fields.IntField(default=1024)

    # ── Turbo Mode ────────────────────────────────────────────────────────────
    turbo_mode_manual               = fields.BooleanField(default=False)
    auto_turbo_enabled              = fields.BooleanField(default=True)
    turbo_inactivity_threshold_mins = fields.IntField(default=5)
    turbo_concurrency               = fields.IntField(default=50)
    crawl_hydration_concurrency     = fields.IntField(default=12)

    # ── Profile analysis loop ─────────────────────────────────────────────────
    profile_analysis_batch_size             = fields.IntField(default=30)
    profile_analysis_staleness_days         = fields.IntField(default=7)
    turbo_profile_analysis_batch_size       = fields.IntField(default=100)
    turbo_feed_fetch_concurrency            = fields.IntField(default=25)
    profile_analysis_inter_batch_sleep_seconds = fields.FloatField(default=2.0)
    profile_analysis_idle_sleep_seconds     = fields.FloatField(default=60.0)

    # ── Graph metrics ─────────────────────────────────────────────────────────
    clustering_top_n    = fields.IntField(default=1000)
    louvain_max_nodes   = fields.IntField(default=10000)
    louvain_resolution  = fields.FloatField(default=1.0)
    bio_keyword_weight                 = fields.IntField(default=5)
    community_keywords_node_sample     = fields.IntField(default=100)
    community_keywords_staleness_days  = fields.IntField(default=30)
    label_prop_max_nodes               = fields.IntField(default=500000)

    class Meta:
        table = "global_settings"

class SavedAccount(Model):
    """A Bluesky account the user has configured in this app."""

    id = fields.IntField(pk=True)
    alias = fields.CharField(max_length=64, unique=True)   # e.g. "main", "alt"
    handle = fields.CharField(max_length=256, unique=True)
    did = fields.CharField(max_length=256, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_synced_at = fields.DatetimeField(null=True)
    auto_sync_enabled = fields.BooleanField(default=True)
    auto_crawl_enabled = fields.BooleanField(default=True)

    class Meta:
        table = "saved_accounts"

    def __str__(self):
        return f"{self.alias} (@{self.handle})"

class CommunityMetadata(Model):
    """Identity and descriptive data for a detected community."""
    id = fields.IntField(pk=True)
    owner = fields.ForeignKeyField("models.SavedAccount", related_name="communities")
    community_id = fields.IntField()
    name = fields.CharField(max_length=256, null=True)
    description = fields.TextField(null=True)
    top_keywords = fields.JSONField(null=True)
    representative_members = fields.JSONField(null=True)
    last_updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "community_metadata"
        unique_together = (("owner", "community_id"),)


class SyncRun(Model):
    """Records each time a sync was performed for an account."""

    id = fields.IntField(pk=True)
    account = fields.ForeignKeyField("models.SavedAccount", related_name="sync_runs")
    started_at = fields.DatetimeField(auto_now_add=True)
    finished_at = fields.DatetimeField(null=True)
    status = fields.CharField(max_length=32, default="running")  # running | done | error
    error_message = fields.TextField(null=True)
    follows_fetched = fields.IntField(default=0)
    followers_fetched = fields.IntField(default=0)
    request_count = fields.IntField(default=0)

    class Meta:
        table = "sync_runs"


class CrawlRun(Model):
    """Records a graph crawl pass so progress survives process restarts."""

    id = fields.IntField(pk=True)
    account = fields.ForeignKeyField("models.SavedAccount", related_name="crawl_runs")
    started_at = fields.DatetimeField(auto_now_add=True)
    finished_at = fields.DatetimeField(null=True)
    status = fields.CharField(max_length=32, default="running")  # running | done | paused | error
    error_message = fields.TextField(null=True)
    batch_size = fields.IntField(default=20)
    candidates_queued = fields.IntField(default=0)
    candidates_completed = fields.IntField(default=0)
    candidates_failed = fields.IntField(default=0)
    candidates_skipped = fields.IntField(default=0)
    discovered_count = fields.IntField(default=0)
    request_count = fields.IntField(default=0)
    last_message = fields.TextField(null=True)

    class Meta:
        table = "crawl_runs"


class Profile(Model):
    """One shared profile row per Bluesky DID."""

    id = fields.IntField(pk=True)
    did = fields.CharField(max_length=256, unique=True)
    handle = fields.CharField(max_length=256)
    display_name = fields.CharField(max_length=256, null=True)
    description = fields.TextField(null=True)
    avatar_url = fields.TextField(null=True)
    banner_url = fields.TextField(null=True)
    profile_url = fields.TextField(null=True)
    followers_count = fields.IntField(default=0)
    follows_count = fields.IntField(default=0)
    posts_count = fields.IntField(default=0)
    account_created_at = fields.DatetimeField(null=True)
    last_post_at = fields.DatetimeField(null=True)
    days_since_post = fields.IntField(null=True)
    sampled_post_count = fields.IntField(default=0)
    repost_count = fields.IntField(default=0)
    original_post_count = fields.IntField(default=0)
    repost_ratio = fields.FloatField(default=0.0)
    is_inactive = fields.BooleanField(default=False)
    is_repost_heavy = fields.BooleanField(default=False)
    last_hydrated_at = fields.DatetimeField(null=True)
    last_analyzed_at = fields.DatetimeField(null=True)
    first_seen_at = fields.DatetimeField(auto_now_add=True)
    labels = fields.TextField(null=True)
    top_keywords = fields.JSONField(null=True)

    class Meta:
        table = "profiles"

    def __str__(self):
        return f"@{self.handle} ({self.did})"


class AccountRelationship(Model):
    """Per-saved-account state for a shared profile."""

    id = fields.IntField(pk=True)
    owner = fields.ForeignKeyField("models.SavedAccount", related_name="relationships")
    profile = fields.ForeignKeyField("models.Profile", related_name="relationships")
    did = fields.CharField(max_length=256)

    i_follow_them = fields.BooleanField(default=False)
    they_follow_me = fields.BooleanField(default=False)
    interacted_with_owner = fields.BooleanField(default=False)

    muted = fields.BooleanField(default=False)
    blocked = fields.BooleanField(default=False)

    is_one_sided_follow = fields.BooleanField(default=False)
    is_follower_only = fields.BooleanField(default=False)

    crawl_tier = fields.IntField(default=1)
    crawl_priority = fields.FloatField(default=0.0)
    last_crawled_at = fields.DatetimeField(null=True)
    crawl_pending_fields = fields.TextField(null=True)
    discovered_via = fields.CharField(max_length=32, null=True)

    flowrank_score = fields.FloatField(null=True)
    clustering_coefficient = fields.FloatField(null=True)
    in_subgraph_degree = fields.IntField(default=0)
    community_id = fields.IntField(null=True)

    first_seen_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "account_relationships"
        unique_together = (("owner", "profile"), ("owner", "did"))

    def __str__(self):
        return f"{self.did} (owner={self.owner_id})"


class FollowEdge(Model):
    """Directed follow link between two DIDs discovered during crawl."""
    id = fields.IntField(pk=True)
    follower_did = fields.CharField(max_length=256)
    followee_did = fields.CharField(max_length=256)
    discovered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "follow_edges"
        unique_together = (("follower_did", "followee_did"),)


class CrawlQueueItem(Model):
    """Persisted graph crawl work item."""

    id = fields.IntField(pk=True)
    account = fields.ForeignKeyField("models.SavedAccount", related_name="crawl_queue_items")
    relationship = fields.ForeignKeyField(
        "models.AccountRelationship",
        related_name="crawl_queue_items",
        null=True,
        on_delete=fields.SET_NULL,
    )
    did = fields.CharField(max_length=256)
    handle = fields.CharField(max_length=256, null=True)
    priority = fields.FloatField(default=0.0)
    tier = fields.IntField(default=0)
    status = fields.CharField(max_length=32, default="pending")
    attempts = fields.IntField(default=0)
    cursor = fields.TextField(null=True)
    pages_fetched = fields.IntField(default=0)
    edges_found = fields.IntField(default=0)
    hydrated_at = fields.DatetimeField(null=True)
    last_error = fields.TextField(null=True)
    locked_at = fields.DatetimeField(null=True)
    completed_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "crawl_queue_items"
        unique_together = (("account", "did"),)


class FilterSet(Model):
    """A named, saved filter configuration stored as a JSON condition tree."""
    id = fields.IntField(pk=True)
    owner = fields.ForeignKeyField("models.SavedAccount", related_name="filter_sets")
    name = fields.CharField(max_length=128)
    icon = fields.CharField(max_length=16, null=True)
    color = fields.CharField(max_length=16, null=True)
    condition_tree = fields.TextField()
    sort_by = fields.CharField(max_length=64, default="handle")
    sort_dir = fields.CharField(max_length=16, default="asc")
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "filter_sets"

    def __str__(self):
        return f"Filter: {self.name}"

class CustomVariable(Model):
    """A named mathematical expression that can be reused in filters."""
    id = fields.IntField(pk=True)
    owner = fields.ForeignKeyField("models.SavedAccount", related_name="custom_variables")
    name = fields.CharField(max_length=64)
    expression_tree = fields.TextField()

    class Meta:
        table = "custom_variables"
        unique_together = (("owner", "name"),)


# ── Chart Studio ──────────────────────────────────────────────────────────────

class ChartDefinition(Model):
    """A saved interactive chart configuration."""

    id          = fields.IntField(pk=True)
    owner       = fields.ForeignKeyField("models.SavedAccount", related_name="chart_definitions")
    name        = fields.CharField(max_length=128)
    icon        = fields.CharField(max_length=8, null=True)
    description = fields.TextField(null=True)
    chart_type  = fields.CharField(max_length=64)           # Registry key e.g. "scatter"
    dimensions  = fields.TextField()                        # JSON AxisConfig map
    filter_set  = fields.ForeignKeyField(
        "models.FilterSet", related_name="charts",
        null=True, on_delete=fields.SET_NULL,
    )
    filter_tree = fields.TextField(null=True)               # Inline JSON filter tree
    aggregation = fields.CharField(max_length=16, null=True) # avg|sum|count|max|min
    limit       = fields.IntField(default=2000)
    sort_by     = fields.CharField(max_length=64, null=True)
    sort_dir    = fields.CharField(max_length=8, default="desc")
    options     = fields.TextField(null=True)               # JSON chart-type-specific options
    pinned      = fields.BooleanField(default=False)
    pin_order   = fields.IntField(null=True)
    created_at  = fields.DatetimeField(auto_now_add=True)
    updated_at  = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "chart_definitions"

    def __str__(self):
        return f"{self.icon or '📊'} {self.name} ({self.chart_type})"
