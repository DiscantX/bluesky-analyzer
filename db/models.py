"""
db/models.py
Tortoise ORM models. One file — easy to extend as the app grows.
"""

from tortoise import fields
from tortoise.models import Model


class SavedAccount(Model):
    """A Bluesky account the user has configured in this app."""

    id = fields.IntField(pk=True)
    alias = fields.CharField(max_length=64, unique=True)   # e.g. "main", "alt"
    handle = fields.CharField(max_length=128, unique=True)
    did = fields.CharField(max_length=256, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_synced_at = fields.DatetimeField(null=True)

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


class TrackedUser(Model):
    """
    One row per (owner_account, tracked_did) pair.
    Stores the latest analysed stats for that user as seen from owner_account.
    """

    id = fields.IntField(pk=True)

    # Which of our saved accounts "owns" this row
    owner = fields.ForeignKeyField("models.SavedAccount", related_name="tracked_users")

    # Identity
    did = fields.CharField(max_length=256)
    handle = fields.CharField(max_length=128)
    display_name = fields.CharField(max_length=256, null=True)
    avatar_url = fields.TextField(null=True)
    profile_url = fields.TextField(null=True)

    # Social counts (from profile)
    followers_count = fields.IntField(default=0)
    follows_count = fields.IntField(default=0)
    posts_count = fields.IntField(default=0)

    # Relationship flags
    i_follow_them = fields.BooleanField(default=False)
    they_follow_me = fields.BooleanField(default=False)

    # Activity analysis (populated after feed sampling)
    last_post_at = fields.DatetimeField(null=True)
    days_since_post = fields.IntField(null=True)
    sampled_post_count = fields.IntField(default=0)   # how many posts we sampled
    repost_count = fields.IntField(default=0)
    original_post_count = fields.IntField(default=0)
    repost_ratio = fields.FloatField(default=0.0)     # 0.0–1.0
    interacted_with_owner = fields.BooleanField(default=False)  # replied/mentioned owner

    # Write-action tracking (for future features)
    muted = fields.BooleanField(default=False)
    blocked = fields.BooleanField(default=False)

    # Derived flags (denormalised for fast filtering)
    is_inactive = fields.BooleanField(default=False)
    is_repost_heavy = fields.BooleanField(default=False)
    is_one_sided_follow = fields.BooleanField(default=False)   # i follow, they don't
    is_follower_only = fields.BooleanField(default=False)      # they follow, i don't

    # Timestamps
    first_seen_at = fields.DatetimeField(auto_now_add=True)
    last_analyzed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "tracked_users"
        unique_together = (("owner", "did"),)

    def __str__(self):
        return f"@{self.handle} (owner={self.owner_id})"
