import asyncio
from typing import Dict, Set, Any

# Shared state for running sync/crawl tasks across API and Background Worker.
# Keys are operation-aware, for example "main:sync" and "main:crawl".
running_tasks: Dict[str, asyncio.Task] = {}


def task_key(alias: str, operation: str) -> str:
    return f"{alias}:{operation}"

class ProgressBus:
    """
    A simple Pub/Sub bus allowing multiple listeners for progress events.
    """
    def __init__(self):
        self.subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self.last_event: Dict[tuple[str, str | None], Any] = {}

    def subscribe(self, alias: str, operation: str | None = None) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        if alias not in self.subscribers:
            self.subscribers[alias] = set()
        self.subscribers[alias].add(queue)
        key = (alias, operation)
        if operation and key in self.last_event:
            queue.put_nowait(self.last_event[key])
        return queue

    def unsubscribe(self, alias: str, queue: asyncio.Queue):
        if alias in self.subscribers:
            self.subscribers[alias].discard(queue)
            if not self.subscribers[alias]:
                del self.subscribers[alias]

    async def emit(self, alias: str, event: Any):
        self.last_event[(alias, event.get("operation"))] = event
        if alias not in self.subscribers:
            return
        
        # Send to all active queues for this alias
        for queue in list(self.subscribers[alias]):
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
