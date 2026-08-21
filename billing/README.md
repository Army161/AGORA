# Billing

Stripe subscriptions and the entitlement layer that enforces them.

**Nothing here is connected to a Stripe account.** No keys are committed, and none can be — the
module reads everything from the environment. Connecting your account is deliberately your step,
not something a tool does on your behalf.

## What the paywall actually gates

| | Free | Team | Enterprise |
| --- | --- | --- | --- |
| Agents per room | **2** | 25 | unlimited |
| Hosted web connector | ✗ | ✓ | ✓ |
| Audit retention | 7 days | 90 days | 10 years |
| Local self-hosted room | ✓ | ✓ | ✓ |

The free tier allows **two** agents on purpose. That is exactly enough to experience the product —
one agent hands off to another — while a real team workflow needs more. A limit of one would make
the tool pointless rather than limited, and nobody upgrades from pointless.

> The coordination engine is MIT licensed and self-hostable. The monetizable surface is **hosting
> and identity**, not the algorithm. Pricing that pretends otherwise invites a fork.

## Setup

<!-- Steps are ordered so nothing can charge a real card until the last one. -->

### 1. Create the products in Stripe

In the Stripe Dashboard, create one **recurring** price per paid plan and copy the price IDs
(`price_...`). Start in **test mode**.

### 2. Set the environment

```bash
export STRIPE_SECRET_KEY=sk_test_...        # test key first
export STRIPE_WEBHOOK_SECRET=whsec_...
export STRIPE_PRICE_TEAM=price_...
export STRIPE_PRICE_ENTERPRISE=price_...    # optional
```

```bash
pip install -r billing/requirements.txt
```

### 3. Run the webhook receiver

```bash
python billing/webhook_server.py --rooms-dir ~/.agora --port 8850
```

Forward test events to it:

```bash
stripe listen --forward-to localhost:8850/stripe/webhook
```

### 4. Test a full purchase

Use Stripe's test card `4242 4242 4242 4242`, any future expiry, any CVC. After checkout completes,
`~/.agora/<workspace>/billing.json` should show the plan as active.

### 5. Go live — the last step, deliberately

```bash
export STRIPE_SECRET_KEY=sk_live_...
export AGORA_STRIPE_LIVE=1        # required, on purpose
```

A live key **without** `AGORA_STRIPE_LIVE=1` raises `LiveKeyRefused`. Charging a real card from a
dev machine is not an error you get to undo, so it takes two decisions rather than one.

Register the production webhook endpoint at `https://your-host/stripe/webhook` and subscribe to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_failed`

## Design notes

**Stripe owns billing; `billing.json` owns access.** They are separate so a Stripe outage cannot
lock a paying customer out of their own room — the last known good entitlement stays on disk and
keeps working.

**`past_due` still grants access.** A failed card starts dunning; it does not lock a team out
mid-workday. Only `canceled` drops to free.

**A cancelled plan degrades to free, it does not fail closed.** Losing access to your own
coordination history because a card expired is a worse outcome than a free tier.

**A reconnecting agent never consumes a new seat.** Otherwise a dropped connection would lock an
existing member out of a room they were already in.

**Webhook signatures are verified against the raw HMAC scheme**, not delegated to the SDK, so the
verification path is testable offline. Replays outside a 300-second tolerance are rejected.

## Tests

```bash
python -m unittest discover -s tests -v
```

24 billing tests, none of which touch Stripe or the network — including tampered payloads, wrong
secrets, replayed events, and the live-key guard.

## Not built yet

- No checkout **UI**. `create_checkout_session()` returns a URL; something has to link to it.
- No enforcement wired into `agora_join` yet — `check_agent_limit()` exists and is tested, but the
  server does not call it, so the OSS path stays unmetered until you decide to switch it on.
- No proration, seat-count sync, or tax configuration.
