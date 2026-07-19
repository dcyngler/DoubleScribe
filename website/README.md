# Double Scribe: marketing site

Static site (no build step) for Double Scribe, using the app's own brand
(blue `#0033CC`, mic icon, chat-bubble transcript preview).

- `public/index.html`: home page (hero, features, download)
- `public/about.html`: why the app exists, project goals, the consent note
- `public/info.html`: how it works, requirements, privacy, FAQ
- `public/styles.css`: shared styles for all three pages
- `public/img/icon.png`: app icon, reused from `double-scribe-app/app/icon.png`

## Preview locally

```
npx serve public
```

## Deploy to Render

A `render.yaml` blueprint lives at the repo root and points at this folder
(`rootDir: website`, `staticPublishPath: public`, no build step).

1. Push this repo to GitHub (already set up as `origin`).
2. In the [Render dashboard](https://dashboard.render.com), **New → Blueprint**,
   pick the `DoubleScribe` repo. Render reads `render.yaml` and creates a
   static site called `double-scribe` automatically.
3. Render gives you a `*.onrender.com` URL immediately, no further config needed.
4. Later, add the custom domain either directly in Render (Settings → Custom Domains)
   or by putting Cloudflare in front of the `.onrender.com` URL as a CNAME.

Every push to the connected branch auto-redeploys.

## Deploy to Cloudflare Pages

One-time login (opens a browser window to authorize):

```
npx wrangler login
```

Deploy:

```
npx wrangler pages deploy public --project-name=double-scribe
```

Wrangler creates the Pages project on first deploy and prints a `*.pages.dev` URL.
Re-run the same command any time you change the site; it deploys a new version.

To use a custom domain, add it in the Cloudflare dashboard under
**Workers & Pages → double-scribe → Custom domains**.

## Donations (Stripe)

The "Donate" button is a plain link to a
[Stripe Payment Link](https://docs.stripe.com/payment-links) — no server
code involved in taking the payment itself. `functions/api/webhook.js` is an
optional Cloudflare Pages Function that logs completed donations if you want
a record of them (Payment Links fire the same `checkout.session.completed`
event a custom Checkout Session would).

### One-time setup

1. In the [Stripe Dashboard](https://dashboard.stripe.com/test/payment-links),
   click **+ New**, add the "Support Double Scribe" product (create it inline
   if it doesn't exist yet — one-time price, e.g. $5 USD), and click **Create link**.
2. Under the link's **After payment** settings, point the confirmation page
   at `https://doublescribe.app/donate-success.html` (and set cancel/back
   behavior to `donate-cancel.html` if offered).
3. Copy the link URL (`https://buy.stripe.com/...`) and paste it over
   `https://buy.stripe.com/REPLACE_ME` in `public/index.html`,
   `public/about.html`, `public/info.html`, and `public/donate-cancel.html`.
4. (Optional, for the webhook logger) `npm install` in this folder, add a
   webhook endpoint in the Dashboard pointed at
   `https://doublescribe.app/api/webhook` listening for
   `checkout.session.completed`, and set these two secrets:
   ```
   npx wrangler pages secret put STRIPE_SECRET_KEY --project-name=double-scribe
   npx wrangler pages secret put STRIPE_WEBHOOK_SECRET --project-name=double-scribe
   ```
5. Deploy (`npx wrangler pages deploy public --project-name=double-scribe`)
   and click Donate to try it with a
   [test card](https://docs.stripe.com/testing#cards).

Repeat with a live-mode Payment Link (and live secrets, if using the
webhook) when you're ready to accept real payments.

### Testing the webhook locally

```
STRIPE_SECRET_KEY=sk_test_... STRIPE_WEBHOOK_SECRET=whsec_... \
  npx wrangler pages dev public --compatibility-flag=nodejs_compat
```

In another terminal, forward webhook events to the local server with the
[Stripe CLI](https://docs.stripe.com/stripe-cli):
```
stripe listen --forward-to localhost:8788/api/webhook
```

## Download analytics

The Download button hits `/api/download`, a Cloudflare Pages Function
(`functions/api/download.js`) that logs the visitor's country (from
Cloudflare's `request.cf`, no IP stored) and `Referer` header to a Workers
Analytics Engine dataset, then redirects to the real installer file. View the
aggregated numbers at `/stats.html`, which calls `functions/api/stats.js`.

### One-time setup

1. Get your account ID from the [Cloudflare dashboard](https://dash.cloudflare.com)
   (right sidebar of any domain overview page, or `npx wrangler whoami`).
2. Create an API token at
   [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
   with **Account → Account Analytics → Read** permission (that's the only
   scope it needs).
3. Generate a long random dashboard token, e.g.:
   ```
   openssl rand -hex 32
   ```
4. Set the three secrets on the Cloudflare Pages project:
   ```
   npx wrangler pages secret put CF_ACCOUNT_ID --project-name=double-scribe
   npx wrangler pages secret put CF_ANALYTICS_API_TOKEN --project-name=double-scribe
   npx wrangler pages secret put STATS_TOKEN --project-name=double-scribe
   ```
5. Deploy, then open `https://doublescribe.app/stats.html`, paste in the
   `STATS_TOKEN` value, and click Load.

The Analytics Engine dataset (`double_scribe_downloads`) is created
automatically on first write — no manual provisioning needed. If the token
ever leaks, rotate it by generating a new random value and re-running the
`STATS_TOKEN` secret put above.

## Before going live

The Download button on the page points to `/downloads/DoubleScribeSetup.exe`, which
doesn't exist yet: no installer has been built. Either:

- Build the installer (see `double-scribe-app/CLAUDE.md` → Distribution) and drop
  `DoubleScribeSetup.exe` into `public/downloads/` before deploying, or
- Point the Download button at a GitHub Releases URL instead (edit `index.html`).
