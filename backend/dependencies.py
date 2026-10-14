import re
import threading
import time
from collections import defaultdict, deque
from typing import Annotated, Optional

from fastapi import Header

from backend import llm
from backend.config import settings
from backend.database import get_db  # noqa: F401  (re-export)
from backend.errors import BadRequestError, RateLimitError

_USER_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_hits: dict = defaultdict(deque)
_lock = threading.Lock()


def get_user_id(x_user_id: Annotated[Optional[str], Header()] = None) -> str:
    """Partitions data per demo user. This is NOT authentication."""
    uid = (x_user_id or settings.default_user_id).strip()
    if not _USER_RE.match(uid):
        raise BadRequestError("X-User-Id must be 1-64 characters: letters, digits, '_' or '-'.")
    return uid


def require_ai_user(x_user_id: Annotated[Optional[str], Header()] = None) -> str:
    """For endpoints that need OpenAI: checks configuration and applies a simple per-user rate limit."""
    uid = get_user_id(x_user_id)
    llm.require_configured()
    now = time.monotonic()
    with _lock:
        q = _hits[uid]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.rate_limit_per_minute:
            raise RateLimitError("Too many AI requests; please wait a minute.")
        q.append(now)
    return uid