# DoubleScribe repo scope

This repo (`dcyngler/DoubleScribe`, public) is the desktop app only — see [double-scribe-app/](double-scribe-app/).

The marketing/donation website is a **separate, private repo**: `dcyngler/website-for-double-scribe`,
checked out locally as a sibling folder at `../website-for-double-scribe`. Website work (HTML/CSS,
Cloudflare Pages Functions, Stripe donation flow, download-stats dashboard, SEO files, etc.) must be
made there, not here. Do not recreate a `website/` folder in this repo or commit site changes to this
repo's history — commit and push them from the `../website-for-double-scribe` checkout instead.
