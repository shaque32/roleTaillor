# Email setup (Resend)

RoleTailor sends three emails: a link to confirm a new account's address, a link to reset a
forgotten password, and a notice that a password was changed. They go through
[Resend](https://resend.com). Nothing else is emailed.

Locally you need none of this. With `RT_EMAIL_PROVIDER=console` (the default) the API writes
each email, including its link, to its log:

```
docker compose logs api | grep "token="
```

## What you need to do once

These steps need your accounts, so they are yours. Allow about 15 minutes plus DNS propagation.

1. **Create a Resend account** at resend.com. The free plan was 3,000 emails a month and 100 a
   day when this was written (November 2026); check the current limits. That is enough for
   launch, since each sign-up sends one email.
2. **Add a sending domain.** In Resend, open Domains, then Add Domain. Use a subdomain such as
   `mail.yourdomain.com`, not the bare domain. It keeps the reputation of these emails
   separate from any other mail you send.
3. **Add the DNS records Resend shows you** at your DNS provider: the DKIM `TXT` record, and the
   SPF `TXT` and `MX` records on the `send` subdomain. Also add a DMARC record if the domain
   does not have one: `TXT _dmarc.yourdomain.com` with `v=DMARC1; p=none; rua=mailto:you@yourdomain.com`.
   Tighten `p` to `quarantine` after a few weeks of clean reports.
4. **Wait for "Verified"** on the domain page. Resend refuses to send from an unverified domain.
5. **Turn off open and click tracking** for the domain (they are off by default). Click
   tracking rewrites links, which would route the one-time links through a tracking redirect.
6. **Create an API key**: API Keys, Create API Key, permission "Sending access", restricted to
   the domain from step 2. Create one key for staging and one for prod.
7. **Set the configuration.**
   - Secret, per environment: `fly secrets set RESEND_API_KEY=re_... -a roletailor-api`
     (staging: `-a roletailor-api-staging`). `deploy/fly/bootstrap.sh` also prompts for it.
   - Non-secret, in `deploy/fly/env/<env>.api.env`: replace the placeholder in
     `RT_EMAIL_FROM=RoleTailor <no-reply@mail.yourdomain.com>`. `RT_EMAIL_PROVIDER=resend` is
     already there.
8. **Deploy and test.** Register with a real address, confirm it from the email, then run
   "Forgot password?" from the sign-in page. Check the Resend dashboard (Emails) if nothing
   arrives.

Staging and prod must use `resend`: outside dev the API refuses to start with any other
provider, with no key, or with a sender still on the `.example` placeholder. The console
provider is for a developer's own machine only, because it writes working one-time links
to the log.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `RT_EMAIL_PROVIDER` | `console` | `console` logs the email (dev only), `resend` sends it |
| `RESEND_API_KEY` | | Resend key (`RT_RESEND_API_KEY` works too). Secret |
| `RT_EMAIL_FROM` | placeholder | Sender, on the verified domain |
| `RT_EMAIL_REPLY_TO` | | Optional reply address |
| `RT_EMAIL_VERIFICATION_TTL_HOURS` | 24 | Lifetime of a confirmation link |
| `RT_PASSWORD_RESET_TTL_MINUTES` | 60 | Lifetime of a reset link |
| `RT_REQUIRE_VERIFIED_EMAIL` | `true` | Tailoring needs a confirmed address |
| `RT_RATE_LIMIT_PASSWORD_RESET_PER_HOUR` | 5 | Reset emails per address per hour |
| `RT_RATE_LIMIT_VERIFICATION_EMAIL_PER_HOUR` | 5 | Confirmation emails per user per hour |

## How the flows behave

- **Sign-up** works as before and signs the user in. A confirmation email goes out after the
  response, so an email outage never fails a sign-up. Until the address is confirmed the user
  can upload resumes and add jobs, but starting a tailoring returns `403 email_unverified`
  and the app shows a banner with a "Resend email" button.
- **Forgot password** always answers the same way, and does the account lookup and the send
  after the response, so neither the answer nor its timing reveals whether an address has an
  account. Past the hourly budget for one address, requests are dropped quietly instead of
  refused, so nobody can block another person's reset.
- **Reset** sets the new password, signs the account out on every device, cancels any other
  reset link, confirms the address (the link proved the inbox), writes an audit entry and
  sends a "password changed" notice.
- **Links** are random 256-bit tokens with an HMAC, stored only as a SHA-256 hash
  (`user_tokens`, migration 007), single use, and expiring. Asking for a new link cancels
  the previous one. The token travels in the URL fragment, which browsers do not send to
  servers, so it stays out of access logs and Referer headers.
- Rotating `RT_SECRET_KEY` invalidates links that were already mailed. Users ask for a new one.

## Known limits

- Sign-up still says "An account with this email already exists" for a taken address.
  Closing that needs sign-up to stop signing users in before they confirm, which is a
  product change.
- Accounts created before this change are unconfirmed and see the banner.
- Expired rows in `user_tokens` are not purged yet. They are inert; the retention job can
  delete rows whose `expires_at` is in the past.

## Using another provider

Add a class with a `send(message)` method next to `ResendProvider` in
`backend/roletailor/mailer/provider.py`, return it from `get_provider()`, and add its name
to `EMAIL_PROVIDERS` in `config.py`. Nothing else changes.
