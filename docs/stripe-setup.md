# Stripe setup

Do everything in **test mode** first (toggle "Test mode" in the Stripe dashboard). Repeat in live mode only after the checklist at the end passes.

## 1. Products and prices

1. Product catalog -> Add product: name "RoleTailor Pro". Add a recurring price: **$9.99 USD / month**. Copy the price id (`price_...`) -> `RT_STRIPE_SUBSCRIPTION_PRICE_ID`.
2. Optional: add a second product "RoleTailor single resume" with a **one-time $0.50 USD** price and copy its id -> `RT_STRIPE_PAY_PER_USE_PRICE_ID`. If left empty the app uses inline price data of `RT_PAY_PER_USE_AMOUNT_MINOR` (50). Note: card fees make $0.50 close to break-even; Stripe's minimum charge is $0.50.

## 2. Customer portal

Settings -> Billing -> Customer portal -> configure and save:
- Allow customers to cancel subscriptions (at end of billing period recommended).
- Allow customers to update payment methods.
- Show invoice history.
- Set the business name, privacy policy and terms links.
- Leave plan switching off (there is only one plan).

## 3. API key and webhook

1. Developers -> API keys: copy the **secret key** (`sk_test_...`) -> `RT_STRIPE_SECRET_KEY`. Never put it in the frontend or commit it.
2. Developers -> Webhooks -> Add endpoint: URL `https://<api-host>/v1/billing/webhook`. Select exactly these events:
   - `checkout.session.completed`
   - `checkout.session.async_payment_succeeded`
   - `checkout.session.async_payment_failed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
   - `charge.refunded`
3. Copy the endpoint's signing secret (`whsec_...`) -> `RT_STRIPE_WEBHOOK_SECRET`.

## 4. Environment variables

```
RT_STRIPE_SECRET_KEY=sk_test_...
RT_STRIPE_WEBHOOK_SECRET=whsec_...
RT_STRIPE_SUBSCRIPTION_PRICE_ID=price_...
RT_STRIPE_PAY_PER_USE_PRICE_ID=price_...   # optional
RT_APP_BASE_URL=https://<web-host>         # checkout and portal return here (/settings#billing)
```
Store them in your host's secret manager, not in the repo. Restart the API after changing them.

## 5. Local testing

```
stripe login
stripe listen --forward-to localhost:8000/v1/billing/webhook   # prints a whsec_ for RT_STRIPE_WEBHOOK_SECRET
stripe trigger checkout.session.completed
stripe trigger invoice.payment_failed
```
`stripe trigger` fixtures do not carry our `organization_id` metadata, so those events are acknowledged but logged as "without a known organization". For a real end-to-end run, use the app: Settings -> Billing -> Subscribe, pay with a test card, and watch the `stripe listen` output.

Test cards (any future expiry, any CVC):
- `4242 4242 4242 4242` succeeds
- `4000 0000 0000 9995` declined (insufficient funds)
- `4000 0025 0000 3155` requires 3D Secure authentication

## 6. Behaviour to know

- Events are deduplicated by event id; a handler that fails returns 500 and Stripe retries, which reprocesses it.
- A canceled subscription is never reactivated by a late `created`/`updated` event.
- Payments through delayed methods stay `pending` (no credit) until `async_payment_succeeded`.
- Bodies over 1 MB are rejected with 413 before signature verification.

## 7. Going live checklist

- [ ] Repeat sections 1-3 in live mode (prices, portal config, webhook endpoint are separate per mode).
- [ ] Replace all four `RT_STRIPE_*` values with live ones; confirm `sk_live_`/`whsec_` are in secrets only.
- [ ] Subscribe for $9.99 with a real card; the webhook endpoint shows the deliveries as 200 and Settings shows the subscription as active.
- [ ] Buy one $0.50 pay-per-use credit, confirm it appears, refund it in Stripe, and confirm the credit is gone.
- [ ] Subscribe, cancel in the portal, and confirm the app shows "Ends <date>".
- [ ] Enable Stripe Radar defaults, email receipts, and failed-payment retry emails (Settings -> Billing).
- [ ] Complete business verification and tax settings (Stripe Tax if you sell where VAT/GST applies).
- [ ] Set a dashboard alert for webhook failures (Developers -> Webhooks -> endpoint -> alerts).
