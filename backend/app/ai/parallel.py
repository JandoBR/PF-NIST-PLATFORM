from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

DEFAULT_CONCURRENCY = 6

_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_slots_size = 0


def concurrency() -> int:
    try:
        value = int(os.environ.get("AI_MAX_CONCURRENCY", DEFAULT_CONCURRENCY))
    except ValueError:
        return DEFAULT_CONCURRENCY
    return max(1, value)


def slot() -> threading.BoundedSemaphore:
    global _slots, _slots_size
    size = concurrency()
    with _lock:
        if _slots is None or _slots_size != size:
            _slots = threading.BoundedSemaphore(size)
            _slots_size = size
        return _slots


def map_ordered[T, R](fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
    items = list(items)
    workers = min(concurrency(), len(items))
    if workers <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(copy_context().run, fn, item) for item in items]
        return [future.result() for future in futures]
