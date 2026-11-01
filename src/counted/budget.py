"""A daily cap on model-backed runs, so a public deployment has a bounded bill.

COUNTED_DAILY_RUNS=0 (the default) means unlimited, which is what local runs and evals use.
"""

from __future__ import annotations

import os
import threading
from datetime import date

LIMIT = int(os.getenv("COUNTED_DAILY_RUNS", "0"))
_lock = threading.Lock()
_day, _used = date.today(), 0


class BudgetExceeded(RuntimeError):
    pass


def spend(units: int = 1) -> None:
    global _day, _used
    if LIMIT <= 0:
        return
    with _lock:
        if date.today() != _day:
            _day, _used = date.today(), 0
        if _used + units > LIMIT:
            raise BudgetExceeded("The public demo has used today's model budget. It resets at midnight UTC; "
                                 "recorded runs still work, or run Counted yourself from the repository.")
        _used += units
