import asyncio
import time
import contextvars
from typing import Dict, Set, Any, List

# Shared state for running sync/crawl tasks across API and Background Worker.
# Keys are operation-aware, for example "main:sync" and "main:crawl".
running_tasks: Dict[str, asyncio.Task] = {}

current_alias_var = contextvars.ContextVar("current_alias", default=None)
current_op_var = contextvars.ContextVar("current_op", default=None)

# Global state for activity tracking to support Auto-Turbo
last_user_activity: float = time.time()

def record_user_activity():
    """
    Updates the global activity timestamp. 
    Called by API routes to signify the user is active.
    """
    global last_user_activity
    last_user_activity = time.time()


class RateTracker:
    """Tracks event counts over a sliding window to compute real-time rates."""
    def __init__(self):
        self.history: List[tuple[float, int]] = []

    def record(self, count: int = 1):
        self.history.append((time.time(), count))

    def get_rate(self, window_seconds: int = 60) -> float:
        now = time.time()
        # Purge old history
        self.history = [h for h in self.history if h[0] > now - window_seconds]
        return round(sum(h[1] for h in self.history), 1)


global_req_tracker = RateTracker()
global_found_tracker = RateTracker()

def task_key(alias: str, operation: str) -> str:
    return f"{alias}:{operation}"

def is_turbo_active() -> bool:
    """
    Determines if the crawler should operate in Turbo mode based on
    manual overrides or inactivity.
    """
    from settings_cache import settings_cache
    
    # Manual toggle always wins
    if settings_cache.get("turbo_mode_manual", False):
        return True
        
    # Auto-Turbo logic: enable if idle for X minutes
    if settings_cache.get("auto_turbo_enabled", False):
        threshold_seconds = settings_cache.get("turbo_inactivity_threshold_mins", 5) * 60
        if (time.time() - last_user_activity) > threshold_seconds:
            return True
            
    return False


class ProgressBus:
    """
    A simple Pub/Sub bus allowing multiple listeners for progress events.
    """
    def __init__(self):
        self.subscribers: Dict[str, Set[tuple[asyncio.Queue, str | None]]] = {}
        self.last_event: Dict[tuple[str, str | None], Any] = {}

    def subscribe(self, alias: str, operation: str | None = None) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        if alias not in self.subscribers:
            self.subscribers[alias] = set()
        self.subscribers[alias].add((queue, operation))
        key = (alias, operation)
        if operation and key in self.last_event:
            queue.put_nowait(self.last_event[key])
        return queue

    def unsubscribe(self, alias: str, queue: asyncio.Queue):
        if alias in self.subscribers:
            self.subscribers[alias] = {s for s in self.subscribers[alias] if s[0] != queue}
            if not self.subscribers[alias]:
                del self.subscribers[alias]

    async def emit(self, alias: str, event: Any):
        op = event.get("operation")
        # Do not cache "heartbeat" log messages as the persistent status for refreshes
        if not event.get("is_heartbeat"):
            self.last_event[(alias, op)] = event
        if alias not in self.subscribers:
            return
        
        # Send to all active queues for this alias
        for queue, sub_op in list(self.subscribers[alias]):
            if sub_op and op != sub_op:
                continue
            try:
                # If queue is full, drop the oldest message to stay real-time
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                queue.put_nowait(event)
            except Exception:
                pass

    def clear(self, alias: str, operation: str | None = None):
        self.last_event.pop((alias, operation), None)

bus = ProgressBus()

def is_running(alias: str) -> bool:
    prefix = f"{alias}:"
    for key, task in running_tasks.items():
        if key.startswith(prefix) and task and not task.done():
            return True

    # Backward compatibility for any older call sites that stored by alias only.
    task = running_tasks.get(alias)
    if task and not task.done():
        return True
    return False


def is_operation_running(alias: str, operation: str) -> bool:
    task = running_tasks.get(task_key(alias, operation))
    return bool(task and not task.done())
