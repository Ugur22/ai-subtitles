"""Helpers for reading error responses from LLM provider APIs."""

import httpx

CREDIT_MARKERS = (
    "credit",
    "insufficient balance",
    "insufficient_quota",
    "payment required",
    "billing",
    "usage limit",
    "spending limit",
)


def provider_error_detail(response: httpx.Response) -> str:
    """The provider's human-readable error, e.g. xAI's out-of-credits notice."""
    try:
        error = response.json().get("error")
        if isinstance(error, dict):
            error = error.get("message")
        if error:
            return str(error)[:300]
    except Exception:
        pass
    return response.text[:300]


def is_credit_exhausted(text: str) -> bool:
    """True when an error message says the account is out of credits or over a spending cap."""
    lowered = text.lower()
    return any(marker in lowered for marker in CREDIT_MARKERS)
