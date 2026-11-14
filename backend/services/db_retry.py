"""Retry database calls that failed because the connection dropped.

The worker keeps one HTTP connection to Supabase for a whole job. When the
server closes it mid-request httpx raises RemoteProtocolError, and the next
request succeeds on a new connection.

A dropped connection does not say whether the request reached the database, so
only wrap calls that are safe to run twice: reads, upserts, and RPCs whose SQL
returns the same answer when repeated.

Timeouts are not retried: postgrest waits up to 120s, so retrying would turn
one slow failure into three. The delays block, so use this in the worker only,
never on the API's event loop.
"""
import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

RETRY_DELAYS_SECONDS = (0.5, 2.0)
CONNECTION_DROPS = (httpx.NetworkError, httpx.RemoteProtocolError)


def with_db_retry(operation: Callable[[], T], *, label: str) -> T:
    for delay in RETRY_DELAYS_SECONDS:
        try:
            return operation()
        except CONNECTION_DROPS as error:
            print(
                f"[DbRetry] {label} lost its connection ({type(error).__name__}: {error}); "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)
    return operation()
