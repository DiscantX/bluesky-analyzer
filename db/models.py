"""
db/models.py
Tortoise ORM models. One file — easy to extend as the app grows.
"""

from tortoise import fields
from tortoise.models import Model


class GlobalSettings(Model):
    """App-wide configuration settings."""
    id = fields.IntField(pk=True)
    inactivity_threshold_days = fields.IntField(default=90)
    repost_ratio_threshold = fields.FloatField(default=0.70)
    feed_sample_size = fields.IntField(default=100)
    sync_staleness_hours = fields.IntField(default=12)
    worker_sweep_interval_seconds = fields.IntField(default=300)
    crawl_concurrency = fields.IntField(default=3)
    min_connection_threshold = fields.IntField(default=3)
    crawl_budget_mb = fields.IntField(default=1024)
    disable_internal_rate_limits = fields.BooleanField(default=False)

    class Meta:
        table = "global_settings"

class SavedAccount(Model):
    """A Bluesky account the user has configured in this app."""

    id = fields.IntField(pk=True)
    alias = fields.CharField(max_length=64, unique=True)   # e.g. "main", "alt"
    handle = fields.CharField(max_length=128, unique=True)
    did = fields.CharField(max_length=256, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_synced_at = fields.DatetimeField(null=True)
    auto_sync_enabled = fields.BooleanField(default=True)
    auto_crawl_enabled = fields.BooleanField(default=True)

    class Meta:
        table = "saved_accounts"

    def __str__(self):
        return f"{self.alias} (@{self.handle})"


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
    handle = fields.CharField(max_length=128)
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
    sampled_post_count = fields.IntField(default=0)   # how many posts we sampled
    repost_count = fields.IntField(default=0)
    original_post_count = fields.IntField(default=0)
    repost_ratio = fields.FloatField(default=0.0)     # 0.0–1.0
    is_inactive = fields.BooleanField(default=False)
    is_repost_heavy = fields.BooleanField(default=False)
    last_hydrated_at = fields.DatetimeField(null=True)
    last_analyzed_at = fields.DatetimeField(null=True)
    first_seen_at = fields.DatetimeField(auto_now_add=True)
    labels = fields.TextField(null=True) # Stored as JSON string

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

    # Write-action tracking (for future features)
    muted = fields.BooleanField(default=False)
    blocked = fields.BooleanField(default=False)

    is_one_sided_follow = fields.BooleanField(default=False)   # i follow, they don't
    is_follower_only = fields.BooleanField(default=False)      # they follow, i don't

    # ── Crawl / Graph status ──────────────────────────────────────────────────
    crawl_tier = fields.IntField(default=1)                    # 0=stub, 1=standard, 2=full
    crawl_priority = fields.FloatField(default=0.0)
    last_crawled_at = fields.DatetimeField(null=True)
    crawl_pending_fields = fields.TextField(null=True)         
    discovered_via = fields.CharField(max_length=32, null=True) # owner_follows, owner_followers, graph_crawl

    # ── Network analysis (computed via NetworkX) ──────────────────────────────
    flowrank_score = fields.FloatField(null=True)
    clustering_coefficient = fields.FloatField(null=True)
    in_subgraph_degree = fields.IntField(default=0)
    community_id = fields.IntField(null=True)

    # Timestamps
    first_seen_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "account_relationships"
        unique_together = (("owner", "profile"), ("owner", "did"))

    def __str__(self):
        return f"{self.did} (owner={self.owner_id})"


class FollowEdge(Model):
    """
    Foundation for the local social graph.
    Stores a directed follow link between two DIDs discovered during crawl.
    """
    id = fields.IntField(pk=True)
    follower_did = fields.CharField(max_length=256)
    followee_did = fields.CharField(max_length=256)
    discovered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "follow_edges"
        unique_together = (("follower_did", "followee_did"),)


class CrawlQueueItem(Model):
    """
    Persisted graph crawl work item.
    One row represents expanding a tracked account's follows list.
    """

    id = fields.IntField(pk=True)
    account = fields.ForeignKeyField("models.SavedAccount", related_name="crawl_queue_items")
    relationship = fields.ForeignKeyField(
        "models.AccountRelationship",
        related_name="crawl_queue_items",
        null=True,
        on_delete=fields.SET_NULL,
    )
    did = fields.CharField(max_length=256)
    handle = fields.CharField(max_length=128, null=True)
    priority = fields.FloatField(default=0.0)
    tier = fields.IntField(default=0)
    status = fields.CharField(max_length=32, default="pending")  # pending | running | done | skipped | error
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
    icon = fields.CharField(max_length=16, null=True)      # Emoji
    color = fields.CharField(max_length=16, null=True)     # Hex color
    condition_tree = fields.TextField()                    # JSON representation of the logic
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
    # JSON representation of the math tree (left_field, extra_terms)
    expression_tree = fields.TextField()

    class Meta:
        table = "custom_variables"
        unique_together = (("owner", "name"),)
