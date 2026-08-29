"""Entitlement store — what a workspace is allowed to do, and who paid for it.

Deliberately mirrors store.py: pure standard library, atomic writes, and a JSON
file on disk. That keeps the paywall testable without Stripe, without a network,
and without an MCP client — the same property that lets the coordination engine
assert on thread contention.

Stripe is the source of truth for *billing*. This file is the source of truth for
*access*, updated from Stripe webhooks. Keeping them separate means a Stripe
outage cannot lock a paying customer out of their own room: the last known good
entitlement stays on disk and keeps working.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, asdict
from typing import Any, Optional

# What the free tier allows. Two agents is deliberate: it is exactly enough to
# experience the product — one agent hands off to another — while a real team
# workflow needs more. A limit of 1 would make the tool pointless rather than
# limited, and nobody upgrades from pointless.
FREE_AGENT_LIMIT = 2

PLANS = {
    "free": {"agent_limit": FREE_AGENT_LIMIT, "hosted_connector": False, "audit_retention_days": 7},
    "team": {"agent_limit": 25, "hosted_connector": True, "audit_retention_days": 90},
    "enterprise": {"agent_limit": 0, "hosted_connector": True, "audit_retention_days": 3650},
}

# Subscription states Stripe considers "still paying". `past_due` is included on
# purpose: a failed card should trigger dunning, not an instant lockout of a
# team mid-workday.
ACTIVE_STATUSES = {"active", "trialing", "past_due"}


class EntitlementError(Exception):
    """Raised when an action exceeds what the current plan allows."""


@dataclass
class Entitlement:
    plan: str = "free"
    status: str = "active"
    customer_id: Optional[str] = None
    subscription_id: Optional[str] = None
    seats: int = 0
    current_period_end: float = 0.0
    updated_at: float = 0.0

    @property
    def limits(self) -> dict:
        return PLANS.get(self.plan, PLANS["free"])

    @property
    def is_active(self) -> bool:
        """A paid plan only counts while Stripe says it is being paid for."""
        if self.plan == "free":
            return True
        return self.status in ACTIVE_STATUSES

    @property
    def effective_plan(self) -> str:
        """The plan actually in force. A lapsed subscription falls back to free
        rather than failing closed — losing access to your own coordination
        history because a card expired is a worse outcome than a free tier."""
        return self.plan if self.is_active else "free"

    @property
    def agent_limit(self) -> int:
        """0 means unlimited."""
        return PLANS.get(self.effective_plan, PLANS["free"])["agent_limit"]

    def allows_hosted_connector(self) -> bool:
        return PLANS.get(self.effective_plan, PLANS["free"])["hosted_connector"]


class EntitlementStore:
    """Reads and writes billing.json inside an Agora workspace."""

    FILENAME = "billing.json"

    def __init__(self, workspace: str):
        self.root = os.path.abspath(os.path.expanduser(workspace))
        os.makedirs(self.root, exist_ok=True)
        self.path = os.path.join(self.root, self.FILENAME)

    def _atomic_write(self, text: str) -> None:
        # Same discipline as store.py: temp file in the SAME directory, then
        # os.replace, which is the only rename atomic on Windows as well as POSIX.
        fd, tmp = tempfile.mkstemp(dir=self.root)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, self.path)

    def load(self) -> Entitlement:
        if not os.path.exists(self.path):
            return Entitlement()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            # A corrupt billing file must not brick the room. Degrade to free
            # rather than raising into every tool call.
            return Entitlement()
        known = {k: v for k, v in data.items() if k in Entitlement.__annotations__}
        return Entitlement(**known)

    def save(self, ent: Entitlement) -> Entitlement:
        ent.updated_at = time.time()
        self._atomic_write(json.dumps(asdict(ent), indent=2))
        return ent

    # ---------- applied from Stripe webhooks ----------
    def apply_subscription(self, *, plan: str, status: str, customer_id: str,
                           subscription_id: str, seats: int = 0,
                           current_period_end: float = 0.0) -> Entitlement:
        """Record what Stripe told us. Called by the webhook handler."""
        return self.save(Entitlement(
            plan=plan, status=status, customer_id=customer_id,
            subscription_id=subscription_id, seats=seats,
            current_period_end=current_period_end,
        ))

    def cancel(self) -> Entitlement:
        ent = self.load()
        ent.status = "canceled"
        return self.save(ent)


def check_agent_limit(workspace: str, current_agent_count: int,
                      joining_agent_id: str, known_agent_ids: Optional[set] = None) -> None:
    """Gate for agora_join. Raises EntitlementError when the room is full.

    An agent already in the room never counts as a new seat, so a reconnect or a
    re-join can never be refused — otherwise a dropped connection would lock an
    existing member out of a room they were already using.
    """
    known_agent_ids = known_agent_ids or set()
    if joining_agent_id in known_agent_ids:
        return

    ent = EntitlementStore(workspace).load()
    limit = ent.agent_limit
    if limit == 0 or current_agent_count < limit:
        return

    raise EntitlementError(
        f"This room is on the '{ent.effective_plan}' plan, which allows {limit} agents. "
        f"'{joining_agent_id}' would be number {current_agent_count + 1}. "
        f"Upgrade at /billing/upgrade, or remove an agent from the room."
    )
