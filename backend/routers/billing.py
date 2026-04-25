"""
Billing & subscription router.

Endpoints:
  - GET  /api/billing/plans     — public pricing tiers (for /pricing page)
  - GET  /api/billing/usage     — caller's current-month usage + plan + admin flag
  - POST /api/billing/checkout  — create a Stripe Checkout session and return its URL
  - POST /api/billing/portal    — create a Stripe Customer Portal session URL
  - POST /api/billing/webhook   — receives Stripe events (subscription created/updated/canceled)

Required env vars:
  STRIPE_SECRET_KEY        - sk_test_... or sk_live_... (in Secret Manager)
  STRIPE_PRO_PRICE_ID      - price_...
  STRIPE_WEBHOOK_SECRET    - whsec_...  (set after registering the webhook)
  PUBLIC_APP_URL           - e.g. https://ai-subs.netlify.app  (used for redirects)
"""

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from middleware.auth import require_auth
from middleware.quota import PLAN_LIMITS, get_usage_snapshot
from services.supabase_service import supabase

router = APIRouter(prefix="/api/billing", tags=["billing"])


# ─── Lazy Stripe client (so the app boots even without Stripe configured) ───

_stripe = None

def _get_stripe():
    """Returns the configured stripe SDK module, or raises 503."""
    global _stripe
    if _stripe is not None:
        return _stripe
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Billing not configured (missing STRIPE_SECRET_KEY).",
        )
    try:
        import stripe as _stripe_mod
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Stripe SDK not installed (pip install stripe).",
        )
    _stripe_mod.api_key = secret
    _stripe = _stripe_mod
    return _stripe


def _public_url() -> str:
    return os.getenv("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")


# ─── Public pricing ─────────────────────────────────────────────────────────

PRICING_TIERS = [
    {
        "id": "free",
        "name": "Free",
        "price_eur_monthly": 0,
        "tagline": "Try it out",
        "features": [
            "60 minutes / month transcription",
            "Search & summaries",
            "Speaker diarization",
            "1 active job at a time",
            "Files up to 30 min",
        ],
        "missing": ["Chat with video", "Scene search", "Multi-LLM access"],
        "cta": "Sign up",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_eur_monthly": 9,
        "price_eur_yearly": 90,
        "tagline": "For creators & journalists",
        "features": [
            "15 hours / month transcription",
            "Chat with video (vision-aware)",
            "Visual scene search (CLIP)",
            "Face tagging + emotion timeline",
            "All LLM providers (Grok, Groq, OpenAI…)",
            "3 concurrent jobs · files up to 3 hours",
            "Priority queue",
        ],
        "missing": [],
        "cta": "Upgrade to Pro",
        "highlighted": True,
    },
]


@router.get("/plans")
async def get_plans():
    """Public — no auth needed. Used by the /pricing page."""
    return {"tiers": PRICING_TIERS}


@router.get("/usage")
@require_auth
async def get_my_usage(request: Request):
    """
    Returns the caller's current-month usage, plan, and limits.
    Used by the frontend to render the usage meter and gate features.
    """
    profile = getattr(request.state, "profile", None)
    snapshot = get_usage_snapshot(profile)
    # Add raw plan-limits config so the frontend can render comparison labels
    snapshot["all_plans"] = {k: v for k, v in PLAN_LIMITS.items()}
    return snapshot


# ─── Stripe Checkout ────────────────────────────────────────────────────────

def _ensure_stripe_customer(profile: dict) -> str:
    """
    Returns the user's Stripe Customer ID, creating one if needed.
    Stamps the new ID back onto user_profiles.
    """
    if profile.get("stripe_customer_id"):
        return profile["stripe_customer_id"]

    stripe = _get_stripe()
    customer = stripe.Customer.create(
        email=profile.get("email"),
        name=profile.get("display_name") or profile.get("email"),
        metadata={"user_id": profile["id"]},
    )
    supabase().table("user_profiles").update({
        "stripe_customer_id": customer.id,
    }).eq("id", profile["id"]).execute()
    return customer.id


@router.post("/checkout")
@require_auth
async def create_checkout_session(request: Request):
    """
    Creates a Stripe Checkout Session for the Pro plan and returns its URL.
    The frontend redirects the user to this URL to complete payment.
    """
    profile = getattr(request.state, "profile", None)
    if not profile:
        raise HTTPException(status_code=401, detail="Authentication required")

    price_id = os.getenv("STRIPE_PRO_PRICE_ID")
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail="Billing not configured (missing STRIPE_PRO_PRICE_ID).",
        )

    stripe = _get_stripe()
    customer_id = _ensure_stripe_customer(profile)
    base = _public_url()

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{base}/?billing=success",
            cancel_url=f"{base}/pricing?billing=canceled",
            allow_promotion_codes=True,
            automatic_tax={"enabled": True},
            client_reference_id=profile["id"],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")

    return {"url": session.url, "session_id": session.id}


@router.post("/portal")
@require_auth
async def create_portal_session(request: Request):
    """
    Returns a Stripe Customer Portal URL where the user can manage their
    subscription (cancel, update payment method, view invoices).
    """
    profile = getattr(request.state, "profile", None)
    if not profile:
        raise HTTPException(status_code=401, detail="Authentication required")

    customer_id = profile.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription. Subscribe first.",
        )

    stripe = _get_stripe()
    base = _public_url()
    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{base}/",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")

    return {"url": portal.url}


# ─── Webhook ────────────────────────────────────────────────────────────────

def _apply_subscription_to_profile(subscription: dict) -> Optional[str]:
    """
    Mirrors a Stripe subscription's state to user_profiles. Returns the
    user_id we updated, or None if no matching customer was found.
    """
    customer_id = subscription.get("customer")
    if not customer_id:
        return None

    client = supabase()
    res = client.table("user_profiles").select("id").eq(
        "stripe_customer_id", customer_id
    ).execute()
    if not res.data:
        print(f"[billing] webhook: unknown customer {customer_id}")
        return None
    user_id = res.data[0]["id"]

    status = subscription.get("status")  # active|past_due|canceled|incomplete|trialing
    plan = "pro" if status in ("active", "trialing", "past_due") else "free"

    period_end_ts = subscription.get("current_period_end")
    period_end_iso = (
        datetime.utcfromtimestamp(period_end_ts).isoformat() if period_end_ts else None
    )

    client.table("user_profiles").update({
        "subscription_plan": plan,
        "subscription_status": status,
        "stripe_subscription_id": subscription.get("id"),
        "current_period_end": period_end_iso,
    }).eq("id", user_id).execute()

    print(f"[billing] webhook: user {user_id} → plan={plan}, status={status}")
    return user_id


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe sends events here when subscriptions change. Verifies the
    signature and mirrors state into user_profiles.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    stripe = _get_stripe()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        _apply_subscription_to_profile(obj)
    elif event_type == "invoice.payment_failed":
        # Mirror status to past_due via subscription update event that follows;
        # log here for visibility.
        print(f"[billing] payment failed for customer {obj.get('customer')}")
    else:
        # Unhandled event type — fine to ignore; Stripe will keep sending.
        print(f"[billing] webhook: ignored event {event_type}")

    return {"received": True}
