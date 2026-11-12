---
version: 1
slug: "app-nimbus-app-templates"
primary_target: "app/nimbus_app/templates"
related_targets: ["docs/dashboard.css"]
---

# Surface brief: Nimbus Index app (all signed-in and public app pages)

Scope: app/nimbus_app/templates (dashboard, history, reports, API access, account, admin, landing, request access, sign in, invite, errors) plus the shared docs/dashboard.css and docs/dashboard.js (public GitHub Pages dashboard uses the same files). Mode: Operate (landing and request access lean Persuade but stay inside the same world).

Audience and job: underwriters and product leads at MGAs and parametric insurers in a free pilot, at office desks in daylight, deciding whether these outage numbers can settle a payout. Engineers second. Must stay untouched: every number, rule, function, route, form, CSP (no inline script), the Example data banner.

## Direction contract

THESIS: Every outage is read the way a cat-bond term sheet reads a trigger: against its attachment points. Refuses the status-page default of white cards, green bars and a big-number tile row.

OWN-WORLD: Navy shell (#13294B) owning the top bar and the page-title band; cool paper ground; white ruled panels with 1px rules, square-ish corners; amber (#E0A526) reserved for attachment points (waiting-period lines) and verification; loss red for down, an in-force green for up, slate secondary ink. Source Serif 4 for titles and defined terms like an offering circular; Public Sans for UI and tabular figures.

STORY: The visitor sees which independent companies judged AWS, whether anything is down, and for each outage whether it crossed a 1 h or 2 h waiting period; they trust it because the rule is stated as defined terms and every record is verifiable.

FIRST VIEWPORT: Navy bar with wordmark and page tabs (amber underline on the current one). Dashboard: navy title band with official state at large serif size and the counted companies with a "signed, chains valid" mark; below, services as one ruled table (state, 24 h failure strip, calls OK, latency), then the trigger ladder of the last 24 h. History: a Summary of Terms table, day squares, then the ladder of every outage.

FORM: Term Sheet, my top-ranked grounded candidate (position 1), chosen as the pick card; seed key 6ca0829b. Signature move: the trigger ladder, each outage a duration bar on a shared scale crossed by amber 1 h and 2 h attachment lines, marked "met" where it passes them.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
