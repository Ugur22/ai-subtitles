"""Retry database calls that failed because the connection dropped.

The worker keeps one HTTP connection to Supabase for a whole job. When the
server closes it mid-request httpx raises a TransportError, and the next
request succeeds on a new connection.

A transport error does not say whether the request reached the database, so
only wrap calls that are safe to run twice: reads, upserts, and RPCs whose SQL
returns the same answer when repeated.
"""
import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 0.5


def with_db_retry(
    operation: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    label: str = "database call",
) -> T:
    """Run operation, retrying on httpx.TransportError with delays of base_delay * 4**n."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except httpx.TransportError as error:
            if attempt == attempts:
                raise
            delay = base_delay * (4 ** (attempt - 1))
            print(
                f"[DbRetry] {label} lost its connection ({type(error).__name__}: {error}); "
                f"retry {attempt}/{attempts - 1} in {delay:.1f}s"
            )
            sleep(delay)
    raise AssertionError("unreachable")
