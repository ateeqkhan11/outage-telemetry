# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: decision-makers at MGAs and parametric insurers (underwriters, product leads) invited to a free pilot (3–5 design partners). They sign in to judge, during the pilot, whether Nimbus Index's outage numbers are trustworthy enough to settle a parametric cloud-outage payout, and what the track record says about pricing. Secondary: their data/engineering staff, who check the API feed, signatures and public keys. Internal: Ateeq and Mike (admins) use the admin pages to invite firms and see who is engaging.

## Product Purpose
Nimbus Index is an independent third-party outage-data verifier for parametric insurance, starting with AWS us-east-1. Probe networks run by different companies (today Microsoft via GitHub Actions and Cloudflare; Google planned) call five AWS services six times a minute; a service-minute counts as down only when probes from two independent operators see it failing. Every result is Ed25519-signed and hash-chained, so anyone can verify it. Success for the app: invited firms sign in, look around, run reports or use the API, and that engagement shows real interest (Mike's market test; sign-in email to firms around 1 Dec 2026).

## Positioning
Independent and provable: no single provider's glitch can trigger a payout, and no one has to take Nimbus Index's word for any number, because every call is signed and checkable in the browser. A probe inside AWS is shown as a reference, never counted.

## Operating Context
Pilot firms receive an invite link by email after a cold-outreach sequence from Mike. Pages: Dashboard (live state, last 24 h), History (months at a glance, one square per day), Reports (up to 31 days, CSV and signed-record downloads), API access (personal keys, /api/v1), Account, Admin (requests, invites, people, activity). Public pages: landing, request access, sign in, invite acceptance. Marketing site nimbusindex.com (Mike, Carrd) links to "Request early access" and "Sign in" on app.nimbusindex.com.

## Capabilities and Constraints
Flask + Jinja templates, one stylesheet set shared with the public GitHub Pages dashboard (docs/dashboard.css, docs/dashboard.js). Strict CSP: scripts and styles from self only (Google Fonts stylesheet allowed), no inline scripts. Terminology: operator, probe network, reference network, official uptime, judged/undecided minutes, waiting period, trigger rules v1. An example-data copy (NIMBUS_DEMO=1) shows six months of simulated data with a banner on every page. Trigger rules are a draft until 13 Nov 2026. No SOC or other certification exists; never claim one.

## Brand Commitments
Name: Nimbus Index (domains nimbusindex.com, getnimbusindex.com for outreach). The user asked to match Mike's marketing site, but as of 12 Nov 2026 it publishes nothing (404; the only archive is a parking page), so there are no logo, colour or font assets yet. OPEN: when Mike shares his site's assets, align with them; until then the app defines the look and Mike's landing page can follow it.

## Evidence on Hand
Live signed data since 8 Nov 2026 (two independent operators counted since 11 Nov 23:18 UTC); backtest of 16 historical us-east-1 outages (backtest/). Absent and never to be fabricated: customers, testimonials, pricing, certifications, partner logos. Simulated six-month data exists only in the labelled example copy.

## Product Principles
1. Trust is shown, not claimed: every number links to the rule that produced it and the signed records behind it.
2. An insurer's question first: was it down, for how long, and did it meet the waiting period.
3. Independence is the product: always show which companies' probes counted and which did not.
4. Honest about gaps: undecided minutes and missing data are shown, never smoothed into "up".
