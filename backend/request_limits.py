"""Process-local limits for anonymous disease searches."""

from __future__ import annotations

import os
import time
from collections import deque

WINDOW_SECONDS = 60
DEFAULT_LIMIT = 6
MAX_TRACKED_CLIENTS = 20_000
_requests: dict[str, deque[float]] = {}


def check_request_limit(client_key: str) -> int | None:
    """Return seconds to wait, or None when this search can proceed.

    Counts are held in memory only and are never written to logs or disk.
    """
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS
    history = _requests.get(client_key)
    if history is None:
        if len(_requests) >= MAX_TRACKED_CLIENTS:
            for key in [key for key, values in _requests.items() if not values or values[-1] <= cutoff]:
                _requests.pop(key, None)
        if len(_requests) >= MAX_TRACKED_CLIENTS:
            return WINDOW_SECONDS
        history = _requests.setdefault(client_key, deque())
    while history and history[0] <= cutoff:
        history.popleft()
    limit = max(1, int(os.getenv("DISEASE_LOOKUP_PER_MINUTE", DEFAULT_LIMIT)))
    if len(history) >= limit:
        return max(1, int(WINDOW_SECONDS - (now - history[0])))
    history.append(now)
    return None
