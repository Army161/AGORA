"""Stripe integration — checkout, webhook verification, and subscription sync.

Everything here is driven by environment variables. No key is ever written to
disk or committed, and the module refuses to run against live keys unless you
opt in explicitly, so a stray test cannot charge a real customer.

Required environment:

    STRIPE_SECRET_KEY        sk_test_... (or sk_live_... with AGORA_STRIPE_LIVE=1)
    STRIPE_WEBHOOK_SECRET    whsec_...
    STRIPE_PRICE_TEAM        price_...   the recurring price for the Team plan
    STRIPE_PRICE_ENTERPRISE  price_...   optional

Install the SDK:

    pip install -r billing/requirements.txt
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Optional

from entitlements import EntitlementStore  # type: ignore

try:
    import stripe  # type: ignore
except ImportError:  # pragma: no cover - exercised only without the SDK installed
    stripe = None


class StripeNotConfigured(Exception):
    """Raised when Stripe is needed but the environment is not set up."""


class LiveKeyRefused(Exception):
    """Raised when a live key is present without an explicit opt-in."""


# Maps a Stripe price id back to the plan it grants. Built from the environment
# so the same code runs in test and live without edits.
def _price_map() -> dict:
    m = {}
    if os.environ.get("STRIPE_PRICE_TEAM"):
        m[os.environ["STRIPE_PRICE_TEAM"]] = "team"
    if os.environ.get("STRIPE_PRICE_ENTERPRISE"):
        m[os.environ["STRIPE_PRICE_ENTERPRISE"]] = "enterprise"
    return m


def configure() -> None:
    """Validate the environment and arm the SDK.

    The live-key guard is the important part: charging a real card from a dev
    machine is not an error you get to undo, so it requires saying so twice.
    """
    if stripe is None:
        raise StripeNotConfigured(
            "the stripe package is not installed. Run: pip install -r billing/requirements.txt")

    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set.")

    if key.startswith("sk_live_") and os.environ.get("AGORA_STRIPE_LIVE") != "1":
        raise LiveKeyRefused(
            "STRIPE_SECRET_KEY is a LIVE key. Set AGORA_STRIPE_LIVE=1 to confirm you intend to "
            "move real money. Use sk_test_... for development.")

    stripe.api_key = key
    stripe.api_version = "2024-06-20"


def is_live() -> bool:
    return os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_live_")


# ---------------------------------------------------------------- checkout --
def create_checkout_session(*, workspace_id: str, plan: str, success_url: str,
                            cancel_url: str, customer_email: Optional[str] = None,
                            seats: int = 1) -> dict:
    """Create a Stripe Checkout session for a subscription.

    workspace_id travels in client_reference_id and in metadata, because the
    webhook has to know WHICH room to entitle. Without it a successful payment
    arrives with no way to tell whose access to unlock.
    """
    configure()

    price_env = {"team": "STRIPE_PRICE_TEAM", "enterprise": "STRIPE_PRICE_ENTERPRISE"}.get(plan)
    if not price_env:
        raise ValueError(f"unknown plan '{plan}'. Expected 'team' or 'enterprise'.")
    price_id = os.environ.get(price_env)
    if not price_id:
        raise StripeNotConfigured(f"{price_env} is not set, so the '{plan}' plan cannot be sold.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": max(1, seats)}],
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=customer_email,
        client_reference_id=workspace_id,
        metadata={"workspace_id": workspace_id, "plan": plan},
        subscription_data={"metadata": {"workspace_id": workspace_id, "plan": plan}},
        allow_promotion_codes=True,
    )
    return {"id": session.id, "url": session.url}


def create_billing_portal_session(*, customer_id: str, return_url: str) -> dict:
    """Let a customer manage or cancel their own subscription.

    Required for compliance in several jurisdictions, and cheaper than handling
    cancellation requests by hand.
    """
    configure()
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return {"url": session.url}


# ----------------------------------------------------------------- webhook --
def verify_webhook(payload: bytes, signature_header: str,
                   secret: Optional[str] = None, tolerance: int = 300) -> dict:
    """Verify a Stripe webhook signature and return the parsed event.

    Implemented against the raw scheme rather than delegating to the SDK so the
    verification path is testable without network access or the stripe package —
    the same reason the coordination engine avoids dependencies.

    Signature failures MUST reject. An unverified webhook is an unauthenticated
    stranger claiming someone paid.
    """
    secret = secret or os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not set.")

    parts = dict(
        p.split("=", 1) for p in signature_header.split(",") if "=" in p
    )
    timestamp = parts.get("t")
    provided = parts.get("v1")
    if not timestamp or not provided:
        raise ValueError("malformed Stripe-Signature header")

    # Replay protection: an old-but-validly-signed event must not be accepted.
    if abs(time.time() - int(timestamp)) > tolerance:
        raise ValueError("webhook timestamp outside tolerance (possible replay)")

    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise ValueError("webhook signature mismatch")

    import json
    return json.loads(payload.decode())


def handle_event(event: dict, workspace_resolver) -> Optional[str]:
    """Apply a verified Stripe event to the right workspace's entitlements.

    workspace_resolver maps a workspace_id to a filesystem path, so hosting
    layout is the caller's concern rather than baked in here.

    Returns a short description of what changed, or None when the event is one
    we deliberately ignore.
    """
    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    workspace_id = (
        obj.get("client_reference_id")
        or (obj.get("metadata") or {}).get("workspace_id")
    )
    if not workspace_id:
        return None

    path = workspace_resolver(workspace_id)
    if not path:
        return None
    store = EntitlementStore(path)

    if etype in ("checkout.session.completed",
                 "customer.subscription.created",
                 "customer.subscription.updated"):
        plan = (obj.get("metadata") or {}).get("plan")
        if not plan:
            # Fall back to resolving via the price, which survives a metadata gap.
            items = (obj.get("items") or {}).get("data") or []
            price_id = items[0].get("price", {}).get("id") if items else None
            plan = _price_map().get(price_id, "team")

        status = obj.get("status") or "active"
        seats = 0
        items = (obj.get("items") or {}).get("data") or []
        if items:
            seats = items[0].get("quantity") or 0

        store.apply_subscription(
            plan=plan,
            status=status,
            customer_id=obj.get("customer") or "",
            subscription_id=obj.get("subscription") or obj.get("id") or "",
            seats=seats,
            current_period_end=float(obj.get("current_period_end") or 0),
        )
        return f"{workspace_id}: {plan} ({status})"

    if etype == "customer.subscription.deleted":
        store.cancel()
        return f"{workspace_id}: canceled"

    if etype == "invoice.payment_failed":
        ent = store.load()
        ent.status = "past_due"
        store.save(ent)
        return f"{workspace_id}: past_due"

    return None
