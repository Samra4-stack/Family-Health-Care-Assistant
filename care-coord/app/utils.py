# utils.py – request‑limit helper
import json
"""Utility functions to enforce the Gemini free‑tier daily request limit (20 calls per day).

The counter is persisted in a JSON file ``request_counter.json`` located at the
workspace root (the parent directory of the ``app`` package).  The file stores a
mapping of date strings (UTC) to the number of Gemini generate‑content calls made
on that date.

Functions:
- ``can_make_request()`` – Returns ``True`` if the current day's count is below
  the limit.
- ``record_request()`` – Increments the counter after a successful LLM call.

Both functions are lightweight and safe for concurrent use in this single‑
process application.
"""

import os
from pathlib import Path
from datetime import datetime, timezone

# Environment flag to bypass quota checks (useful for testing)
FORCE_ALLOW = os.getenv("FORCE_ALLOW", "0").lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Path to the request‑counter file — same directory as the project root (care‑coord).
REQUEST_COUNTER_FILE = Path(__file__).parent.parent / "request_counter.json"

# Daily request limit for Gemini free‑tier. Can be overridden via the environment variable DAILY_LIMIT.
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "20"))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _today() -> str:
    """Return today's date as an ISO‑format string (YYYY‑MM‑DD) in UTC."""
    return datetime.now(timezone.utc).date().isoformat()


def _load_counter() -> dict:
    """Load the counter JSON, returning an empty dict if the file does not exist."""
    if REQUEST_COUNTER_FILE.exists():
        try:
            return json.loads(REQUEST_COUNTER_FILE.read_text(encoding="utf-8"))
        except Exception:
            # Corrupted file – start fresh.
            return {}
    return {}


def _save_counter(data: dict) -> None:
    """Write the counter data back to the JSON file."""
    REQUEST_COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    REQUEST_COUNTER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def can_make_request() -> bool:
    """Return ``True`` if we are under the daily quota or FORCE_ALLOW is set.

    If the environment variable ``FORCE_ALLOW`` is true, the quota check is bypassed.
    """
    if FORCE_ALLOW:
        return True
    data = _load_counter()
    today = _today()
    count = data.get(today, 0)
    return count < DAILY_LIMIT


def record_request() -> None:
    """Increment today's request counter.

    This should be called **only after** a Gemini request has succeeded.
    """
    data = _load_counter()
    today = _today()
    data[today] = data.get(today, 0) + 1
    _save_counter(data)

def reset_counter() -> None:
    """Reset the request counter for today (useful for testing)."""
    data = _load_counter()
    today = _today()
    data[today] = 0
    _save_counter(data)
