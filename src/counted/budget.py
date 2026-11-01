"""Daily caps on paid calls, so a public deployment has a bounded bill.

Two pools: model-backed runs (COUNTED_DAILY_RUNS) and read-aloud requests (COUNTED_DAILY_SPEECH).
0 (the default) means unlimited, which is what local runs and evals use.
"""

from __future__ import annotations

import os
import threading
from datetime import date

LIMITS = {"runs": int(os.getenv("COUNTED_DAILY_RUNS", "0")), "speech": int(os.getenv("COUNTED_DAILY_SPEECH", "0"))}
LIMIT = LIMITS["runs"]
_lock = threading.Lock()
_day = date.today()
_used = {pool: 0 for pool in LIMITS}

_MESSAGES = {
    "runs": "The public demo has used today's model budget. It resets at midnight UTC; recorded runs still work, "
            "or run Counted yourself from the repository.",
    "speech": "The public demo has used today's read-aloud budget. It resets at midnight UTC; the packet can still be "
              "read and downloaded.",
}


class BudgetExceeded(RuntimeError):
    pass


def spend(units: int = 1, pool: str = "runs") -> None:
    global _day
    limit = LIMITS.get(pool, 0)
    if limit <= 0:
        return
    with _lock:
        if date.today() != _day:
            _day = date.today()
            for k in _used:
                _used[k] = 0
        if _used[pool] + units > limit:
            raise BudgetExceeded(_MESSAGES[pool])
        _used[pool] += units
