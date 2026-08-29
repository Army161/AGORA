"""Tests for the paywall.

None of these touch Stripe or the network. Entitlements are plain files and
webhook verification is the documented HMAC scheme, so the whole billing path is
testable offline — which is the only way a paywall gets exercised often enough
to be trusted.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "billing"))

from entitlements import (  # noqa: E402
    Entitlement, EntitlementStore, EntitlementError,
    check_agent_limit, FREE_AGENT_LIMIT, PLANS,
)
import stripe_gateway  # noqa: E402


class BillingTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="agora-billing-")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestEntitlementDefaults(BillingTestCase):
    def test_missing_file_is_free_not_an_error(self):
        """A room that never paid must still work."""
        ent = EntitlementStore(self.root).load()
        self.assertEqual(ent.plan, "free")
        self.assertTrue(ent.is_active)
        self.assertEqual(ent.agent_limit, FREE_AGENT_LIMIT)

    def test_corrupt_file_degrades_to_free(self):
        """A broken billing file must not brick the room."""
        store = EntitlementStore(self.root)
        with open(store.path, "w", encoding="utf-8") as f:
            f.write("{ not json at all")
        self.assertEqual(store.load().plan, "free")

    def test_unknown_fields_are_ignored(self):
        """Stripe adds fields over time; an unknown key must not crash load."""
        store = EntitlementStore(self.root)
        with open(store.path, "w", encoding="utf-8") as f:
            json.dump({"plan": "team", "status": "active", "some_new_field": 1}, f)
        self.assertEqual(store.load().plan, "team")


class TestPlanEnforcement(BillingTestCase):
    def test_free_tier_blocks_the_third_agent(self):
        with self.assertRaises(EntitlementError) as ctx:
            check_agent_limit(self.root, current_agent_count=FREE_AGENT_LIMIT,
                              joining_agent_id="third")
        self.assertIn("free", str(ctx.exception))

    def test_free_tier_allows_up_to_the_limit(self):
        check_agent_limit(self.root, current_agent_count=FREE_AGENT_LIMIT - 1,
                          joining_agent_id="second")

    def test_existing_agent_never_counts_as_a_new_seat(self):
        """A reconnect must never be refused, or a dropped connection locks an
        existing member out of a room they were already in."""
        check_agent_limit(self.root, current_agent_count=99,
                          joining_agent_id="already-here",
                          known_agent_ids={"already-here"})

    def test_paid_plan_raises_the_limit(self):
        EntitlementStore(self.root).apply_subscription(
            plan="team", status="active", customer_id="cus_1", subscription_id="sub_1")
        check_agent_limit(self.root, current_agent_count=10, joining_agent_id="eleventh")

    def test_enterprise_is_unlimited(self):
        EntitlementStore(self.root).apply_subscription(
            plan="enterprise", status="active", customer_id="cus_1", subscription_id="sub_1")
        check_agent_limit(self.root, current_agent_count=5000, joining_agent_id="many")

    def test_canceled_subscription_falls_back_to_free(self):
        store = EntitlementStore(self.root)
        store.apply_subscription(plan="team", status="active",
                                 customer_id="cus_1", subscription_id="sub_1")
        store.cancel()
        ent = store.load()
        self.assertEqual(ent.effective_plan, "free")
        self.assertFalse(ent.allows_hosted_connector())

    def test_past_due_still_works(self):
        """A failed card should start dunning, not lock a team out mid-workday."""
        EntitlementStore(self.root).apply_subscription(
            plan="team", status="past_due", customer_id="cus_1", subscription_id="sub_1")
        ent = EntitlementStore(self.root).load()
        self.assertTrue(ent.is_active)
        self.assertEqual(ent.effective_plan, "team")

    def test_hosted_connector_is_a_paid_feature(self):
        self.assertFalse(Entitlement().allows_hosted_connector())
        EntitlementStore(self.root).apply_subscription(
            plan="team", status="active", customer_id="c", subscription_id="s")
        self.assertTrue(EntitlementStore(self.root).load().allows_hosted_connector())


class TestWebhookVerification(BillingTestCase):
    SECRET = "whsec_test_secret"

    def _sign(self, payload: bytes, timestamp=None, secret=None):
        ts = str(int(timestamp or time.time()))
        sig = hmac.new((secret or self.SECRET).encode(),
                       f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def test_valid_signature_is_accepted(self):
        payload = json.dumps({"type": "checkout.session.completed"}).encode()
        event = stripe_gateway.verify_webhook(payload, self._sign(payload), secret=self.SECRET)
        self.assertEqual(event["type"], "checkout.session.completed")

    def test_tampered_payload_is_rejected(self):
        """The whole point: an unverified webhook is a stranger claiming payment."""
        payload = json.dumps({"type": "checkout.session.completed"}).encode()
        header = self._sign(payload)
        tampered = json.dumps({"type": "checkout.session.completed", "evil": True}).encode()
        with self.assertRaises(ValueError):
            stripe_gateway.verify_webhook(tampered, header, secret=self.SECRET)

    def test_wrong_secret_is_rejected(self):
        payload = b'{"type":"x"}'
        with self.assertRaises(ValueError):
            stripe_gateway.verify_webhook(payload, self._sign(payload, secret="whsec_other"),
                                          secret=self.SECRET)

    def test_replayed_old_event_is_rejected(self):
        payload = b'{"type":"x"}'
        old = self._sign(payload, timestamp=time.time() - 9999)
        with self.assertRaises(ValueError):
            stripe_gateway.verify_webhook(payload, old, secret=self.SECRET)

    def test_malformed_header_is_rejected(self):
        with self.assertRaises(ValueError):
            stripe_gateway.verify_webhook(b"{}", "garbage", secret=self.SECRET)


class TestEventHandling(BillingTestCase):
    def _resolver(self, _wid):
        return self.root

    def test_checkout_completed_grants_the_plan(self):
        event = {"type": "checkout.session.completed", "data": {"object": {
            "client_reference_id": "room-1", "customer": "cus_1", "subscription": "sub_1",
            "status": "active", "metadata": {"workspace_id": "room-1", "plan": "team"}}}}
        result = stripe_gateway.handle_event(event, self._resolver)
        self.assertIn("team", result)
        self.assertEqual(EntitlementStore(self.root).load().effective_plan, "team")

    def test_subscription_deleted_revokes_access(self):
        EntitlementStore(self.root).apply_subscription(
            plan="team", status="active", customer_id="cus_1", subscription_id="sub_1")
        event = {"type": "customer.subscription.deleted", "data": {"object": {
            "id": "sub_1", "customer": "cus_1", "metadata": {"workspace_id": "room-1"}}}}
        stripe_gateway.handle_event(event, self._resolver)
        self.assertEqual(EntitlementStore(self.root).load().effective_plan, "free")

    def test_payment_failed_marks_past_due_without_locking_out(self):
        EntitlementStore(self.root).apply_subscription(
            plan="team", status="active", customer_id="cus_1", subscription_id="sub_1")
        event = {"type": "invoice.payment_failed", "data": {"object": {
            "customer": "cus_1", "metadata": {"workspace_id": "room-1"}}}}
        stripe_gateway.handle_event(event, self._resolver)
        ent = EntitlementStore(self.root).load()
        self.assertEqual(ent.status, "past_due")
        self.assertEqual(ent.effective_plan, "team")

    def test_event_without_workspace_id_is_ignored(self):
        """An event we cannot attribute must change nothing, not guess."""
        event = {"type": "checkout.session.completed", "data": {"object": {}}}
        self.assertIsNone(stripe_gateway.handle_event(event, self._resolver))

    def test_unrelated_event_is_ignored(self):
        event = {"type": "customer.created", "data": {"object": {
            "client_reference_id": "room-1"}}}
        self.assertIsNone(stripe_gateway.handle_event(event, self._resolver))


class TestLiveKeyGuard(BillingTestCase):
    def setUp(self):
        super().setUp()
        self._saved = {k: os.environ.get(k) for k in
                       ("STRIPE_SECRET_KEY", "AGORA_STRIPE_LIVE")}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    @unittest.skipIf(stripe_gateway.stripe is None, "stripe SDK not installed")
    def test_live_key_refused_without_explicit_optin(self):
        """Charging a real card from a dev machine should take two decisions."""
        os.environ["STRIPE_SECRET_KEY"] = "sk_live_fake_for_test"
        os.environ.pop("AGORA_STRIPE_LIVE", None)
        with self.assertRaises(stripe_gateway.LiveKeyRefused):
            stripe_gateway.configure()

    def test_is_live_detects_key_prefix(self):
        os.environ["STRIPE_SECRET_KEY"] = "sk_live_fake_for_test"
        self.assertTrue(stripe_gateway.is_live())
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
        self.assertFalse(stripe_gateway.is_live())


class TestPlanTable(unittest.TestCase):
    def test_every_plan_declares_every_limit(self):
        for name, limits in PLANS.items():
            for key in ("agent_limit", "hosted_connector", "audit_retention_days"):
                self.assertIn(key, limits, f"plan '{name}' is missing '{key}'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
