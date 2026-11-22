"""Build the public Methodology page (site/methodology/index.html) from the rules file.

  python3 scripts/build_methodology.py           write the page
  python3 scripts/build_methodology.py --check   exit 1 if the committed page differs from what the rules produce

Inputs: trigger_v1_rolling.json (the rules), copy/methodology-changelog.md (dated changes) and keys/<network>.pub
(probe network public keys). The page is committed; tests/test_site.py fails if it drifts from this output, so edit
the inputs and regenerate rather than editing the HTML. Bad inputs raise InputError with a clear message (exit 2).

Section ids are a contract: the app links to them (for example #when-it-does-not-fire). Do not rename them.
Standard library only (the server runs this with the system python3).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "methodology" / "index.html"
APP = "https://app.nimbusindex.com"

APPROVED_LINE = ("A reference index in development, built on selected AWS us-east-1 API checks, "
                 "with early data collection under way.")

# Probe networks in scope today: (network id in the rules file, where it runs, date it started).
# Companies come from the rules file's "operators" map; whether a network counts comes from "reference_networks".
NETWORKS: List[Tuple[str, str, str]] = [
    ("github", "GitHub Actions", "8 Nov 2026"),
    ("cloudflare", "Cloudflare Workers", "11 Nov 2026"),
    ("aws", "AWS Lambda, Oregon (us-west-2)", "8 Nov 2026"),
]
# Rounds of checks per minute: the PROBE_ROUNDS default in probe/run.py, workers/src/index.js and aws_lambda/handler.py.
ROUNDS_PER_MINUTE = 6

COMPANY = {"microsoft": "Microsoft", "cloudflare": "Cloudflare", "google": "Google", "aws": "AWS",
           "independent-vps": "An independent VPS host", "local": "Local test machine"}
SERVICE = {"s3": "S3", "dynamodb": "DynamoDB", "lambda": "Lambda", "ec2": "EC2", "sts": "STS"}
FAIL_KIND = {"server_error": "a server error (HTTP 5xx)", "timeout": "a timeout", "network": "no connection",
             "throttled": "throttling (HTTP 429 or an AWS throttling error such as ThrottlingException)"}
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}
KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")                  # Ed25519 public key, base64
DATE_RE = re.compile(r"^\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$")


class InputError(ValueError):
    """The rules file, change log or a key file cannot be rendered."""


# ---------- formatting helpers ----------

def pct(share: float) -> str:
    v = share * 100
    return f"{v:.0f}%" if abs(v - round(v)) < 1e-9 else f"{v:g}%"


def minutes_text(n: int) -> str:
    return "1 minute" if n == 1 else f"{n} minutes"


def duration(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def word(n: int) -> str:
    return WORDS.get(n, str(n))


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def join_words(items: List[str], last: str = "and") -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def inline_md(text: str) -> str:
    """Escape, then turn `code` into <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(text, quote=False))


# ---------- inputs ----------

def parse_changelog(md: str) -> List[Tuple[str, List[str]]]:
    """Free text is allowed before the first "## " date heading; after it, only "- " lines and blank lines."""
    entries: List[Tuple[str, List[str]]] = []
    for n, line in enumerate(md.splitlines(), 1):
        if line.startswith("## "):
            date = line[3:].strip()
            if not DATE_RE.match(date):
                raise InputError(f"change log line {n}: date must look like '22 Nov 2026', got {date!r}")
            entries.append((date, []))
        elif not entries:
            if line.startswith("- "):
                raise InputError(f"change log line {n}: change listed before any '## <date>' heading")
        elif line.startswith("- ") and line[2:].strip():
            entries[-1][1].append(line[2:].strip())
        elif line.strip():
            raise InputError(f"change log line {n}: expected '- <change>' or '## <date>', got {line!r}")
    for date, items in entries:
        if not items:
            raise InputError(f"change log: {date} has no changes listed")
    if not entries:
        raise InputError("change log: no dated entries")
    return entries


def read_keys(keys_dir: Path) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for net, _, _ in NETWORKS:
        p = keys_dir / f"{net}.pub"
        if not p.is_file():
            out[net] = None
            continue
        key = p.read_text(encoding="utf-8").strip()
        if not KEY_RE.match(key):
            raise InputError(f"{p}: not an Ed25519 public key in base64 (43 characters and '=')")
        out[net] = key
    return out


def validate(rules: dict) -> None:
    defs = rules.get("definitions") or {}
    if not defs:
        raise InputError("rules: no definitions")
    if rules.get("default_definition", "degraded") not in defs:
        raise InputError(f"rules: default_definition {rules.get('default_definition')!r} is not in definitions")
    missing = [net for net, _, _ in NETWORKS if net not in rules.get("operators", {})]
    if missing:
        raise InputError(f"rules: no operator for network(s) {', '.join(missing)} in 'operators'")
    for k in ("version", "operators_required", "services", "region", "fail_kinds", "recovery_minutes",
              "waiting_periods_min", "coverage_rule"):
        if k not in rules:
            raise InputError(f"rules: missing {k!r}")


# ---------- page ----------

def render(rules: dict, changelog_md: str, keys: Dict[str, Optional[str]]) -> str:
    validate(rules)
    version = escape(rules["version"])
    ver = f'<p class="sec-foot">Rules version <code>{version}</code></p>'
    need = int(rules["operators_required"])
    companies = "1 company" if need == 1 else f"{need} companies"
    defs = rules["definitions"]
    default_def = rules.get("default_definition", "degraded")
    services = [SERVICE.get(s, s) for s in rules["services"]]
    region = escape(rules["region"])
    reference = list(rules.get("reference_networks", []))
    operators = rules["operators"]
    cov = rules["coverage_rule"]
    waits = [duration(w) for w in rules["waiting_periods_min"]]
    recovery = int(rules["recovery_minutes"])
    fail_kinds = list(rules["fail_kinds"])
    kinds = [FAIL_KIND.get(k, k.replace("_", " ")) for k in fail_kinds]
    in_scope = [(net, runs_on, since, COMPANY.get(operators[net], operators[net])) for net, runs_on, since in NETWORKS]
    counted = [n for n in in_scope if n[0] not in reference]
    refs = [n for n in in_scope if n[0] in reference]

    # ----- What counts as down: one column per definition, Hard down first -----
    order = [k for k in ("hard_down", "degraded") if k in defs] + [k for k in defs if k not in ("hard_down", "degraded")]
    cols, windows = [], []
    for key in order:
        d = defs[key]
        label = escape(d.get("label", key))
        default = ' <span class="tag">Default</span>' if key == default_def else ""
        share, window = pct(d["window_fail_share"]), minutes_text(int(d["window_minutes"]))
        windows.append(f"{window} for {label}")
        cols.append(
            f'<div><h3>{label}{default}</h3>'
            f'<p>At least {companies} each see {share} or more of their calls to a Service fail over the last {window}.</p>'
            f'<dl><dt>Calls failing</dt><dd>{share} or more</dd>'
            f'<dt>Over the last</dt><dd>{window}</dd>'
            f'<dt>Seen by</dt><dd>{need} or more companies</dd></dl></div>')
    n_defs = len(order)
    defs_intro = (f"{cap(word(n_defs))} definitions are reported side by side, so a policy can name the one it uses."
                  if n_defs > 1 else "One definition is used.")

    failed = f"A call counts as failed when it gets {join_words(kinds, 'or')}."
    if "throttled" in fail_kinds:
        failed += (" Throttling is the one client error that counts. Any other client error (HTTP 4xx, such as bad"
                   " credentials) shows that AWS answered, so it never counts.")
    else:
        failed += " A client error (HTTP 4xx) shows that AWS answered, so it never counts."

    # ----- Companies: networks in scope grouped by company -----
    by_company: Dict[str, List[str]] = {}
    for net, runs_on, _, company in counted:
        by_company.setdefault(company, []).append(runs_on)
    shared = [f"{join_words(nets)} {'both' if len(nets) == 2 else 'all'} run on {company}"
              for company, nets in by_company.items() if len(nets) > 1]
    if shared:
        companies_line = "Networks run by the same company count once: " + "; ".join(shared) + "."
    else:
        companies_line = ("Networks run by the same company count once. Each counted network in scope today is run by"
                          " a different company: " + join_words([f"{r} by {c}" for _, r, _, c in counted]) + ".")

    # ----- Probe network tables -----
    scope_rows, key_rows = [], []
    for net, runs_on, since, company in in_scope:
        status = "Shown, never counted (reference)" if net in reference else "Counted"
        scope_rows.append(
            f'<tr><td class="term">{escape(runs_on)}</td><td data-label="Company">{escape(company)}</td>'
            f'<td data-label="Counted">{status}</td><td data-label="Data since" class="num">{since}</td></tr>')
        k = keys.get(net)
        key_cell = (f'<span class="key">{escape(k)}</span>' if k
                    else '<span class="muted">Key not yet published for this network.</span>')
        key_rows.append(f'<tr><td class="term">{escape(runs_on)}</td><td data-label="Public key">{key_cell}</td></tr>')
    counted_companies = sorted({c for _, _, _, c in counted})

    log = "".join(
        f'<div><dt>{escape(date)}</dt><dd><ul>{"".join(f"<li>{inline_md(i)}</li>" for i in items)}</ul></dd></div>'
        for date, items in parse_changelog(changelog_md))

    two = cap(word(need))
    companies_heading = f"{two} {'company' if need == 1 else 'companies'} must see it"

    reference_section = reference_case = ""
    if reference:
        names = escape(join_words([r for _, r, _, _ in refs] or reference))
        reference_section = f"""
<section class="sec" id="rule-reference-network">
  <h2>The reference network is shown, never counted</h2>
  <p>The reference network ({names}) runs inside AWS. Its results are shown for reference but never counted, because a probe inside AWS cannot judge AWS independently.</p>
  {ver}
</section>
"""
        reference_case = ('<li><span class="case">The reference network fails</span><span>The AWS-hosted reference probe'
                          ' sees failures that the counted networks do not. It is never counted, so'
                          ' <span class="outcome">no outage</span> is called.</span></li>')

    toc = [("rule-what-counts-as-down", "What counts as down"),
           ("rule-two-companies", companies_heading),
           ("rule-start-and-end", "When an outage starts and ends"),
           ("timing-and-counting", "Timing and counting")]
    if reference:
        toc.append(("rule-reference-network", "The reference network"))
    toc += [("rule-coverage", "Enough data, or no call"),
            ("when-it-does-not-fire", "When it does not fire"),
            ("why-clocks-differ", "Why clocks differ"),
            ("scope", "Current scope"),
            ("public-keys", "Public keys"),
            ("change-log", "Change log")]
    toc_html = "".join(f'<li><a href="#{i}">{escape(t)}</a></li>' for i, t in toc)
    one_company_case = (f"A {escape(counted[0][3])}-run probe sees Lambda failing; {escape(counted[1][3])}’s sees it"
                        f" working." if len(counted) >= 2 else "One company’s probe sees Lambda failing; the others see it working.")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Methodology · Nimbus Index</title>
<meta name="description" content="How Nimbus Index decides when an AWS us-east-1 outage started and ended: the rules as designed, when they do not fire, current scope with dates, public keys and change log.">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#111A2A" media="(prefers-color-scheme: dark)">
<link rel="preload" href="/assets/fonts/source-serif-4-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/site.css">
</head>
<body>
<!-- Generated by scripts/build_methodology.py from trigger_v1_rolling.json, copy/methodology-changelog.md and keys/*.pub. Do not edit by hand. -->
<a class="skip" href="#main">Skip to content</a>

<header class="top">
  <div class="wrap">
    <a class="wordmark" href="/">Nimbus Index</a>
    <nav aria-label="Site">
      <a class="nav" href="/methodology/" aria-current="page">Methodology</a>
      <a class="nav" href="{APP}/sign-in">Sign in</a>
      <a class="btn btn-primary" href="{APP}/request-access">Request early access</a>
    </nav>
  </div>
</header>

<div class="wrap">
<div class="page-head">
  <h1>Methodology</h1>
  <p class="lede">{APPROVED_LINE}</p>
  <div class="tags"><span class="tag">Pending independent review (no reviewer appointed yet)</span><span class="version">Rules version <code>{version}</code></span></div>
  <p class="phone-cta"><a class="btn btn-primary" href="{APP}/request-access">Request early access</a></p>
</div>

<div class="doc">
<nav class="toc" aria-label="On this page">
  <p>On this page</p>
  <ol>{toc_html}</ol>
</nav>

<main id="main">

<section class="sec" id="about">
  <h2>About this page</h2>
  <p>This page sets out the rules as designed. It is generated from the rules file, so every number below is the number the index uses. The rules are a draft until an independent reviewer has checked them. What the index covers today is listed separately, with dates, under <a href="#scope">Current scope</a>.</p>
</section>

<section class="sec" id="rule-what-counts-as-down">
  <h2>What counts as down</h2>
  <p class="intro">{defs_intro}</p>
  <div class="pair">{"".join(cols)}</div>
  <p class="after">{escape(failed)} The Services checked are {join_words(services)}, in {region}.</p>
  {ver}
</section>

<section class="sec" id="rule-two-companies">
  <h2>{escape(companies_heading)}</h2>
  <p>A Service is down only when the probe networks of at least {companies} each see it fail, by the definition above, at the same time.{" One company’s view is never enough." if need > 1 else ""}</p>
  <p>{escape(companies_line)}</p>
  <p>A probe network’s view counts only while its own connection works. In every round it also calls a site outside AWS. If that call fails, the problem is on the probe’s side: the round is set aside and is not counted as an AWS failure.</p>
  {ver}
</section>

<section class="sec" id="rule-start-and-end">
  <h2>When an outage starts and ends</h2>
  <p>An outage starts in the first minute the rule above calls a Service down. It ends at the last minute called down, once {recovery} later {'minute has' if recovery == 1 else 'minutes have'} been called up, with no further minute called down.</p>
  <p>The duration runs from the first minute called down to the last, inclusive. It is read against waiting periods of {join_words(waits)}.</p>
  {ver}
</section>

<section class="sec" id="timing-and-counting">
  <h2>Timing and counting</h2>
  <ul class="plain">
    <li>All times are UTC. Every check is filed under the UTC minute in which it was made; minutes start at :00 seconds.</li>
    <li>Each probe network makes {ROUNDS_PER_MINUTE} rounds of checks a minute by default, evenly spaced. A round is one call to each of the {len(services)} Services plus the call to a site outside AWS.</li>
    <li>A company’s share of failed calls to a Service is worked out over all the usable calls its networks made in the window of the definition ({join_words(windows)}), counting back from the current minute.</li>
    <li>There is no minimum number of calls. A single usable call in the window is enough for a company to be judged for that Service.</li>
    <li>Each Service is judged on its own. The region is down while any Service is down, up only while every Service is up, and otherwise not enough data.</li>
    <li>Minutes with not enough data between the first and last minute called down stay inside the outage and count toward its duration, and so toward the waiting period. They do not end it. Minutes with not enough data after the last minute called down do not extend it.</li>
  </ul>
  {ver}
</section>
{reference_section}
<section class="sec" id="rule-coverage">
  <h2>Enough data, or no call</h2>
  <p>An official call needs {companies}, each covering {pct(cov["min_share"])} or more of the last {cov["window_hours"]} h and each reporting within the last {minutes_text(cov["max_age_min"])}.</p>
  <p>If that is not met, the state is “not enough data”. Missing data is never treated as up.</p>
  {ver}
</section>

<section class="sec" id="when-it-does-not-fire">
  <h2>When it does not fire</h2>
  <p class="intro">Worked cases where the rules do not call an outage.</p>
  <ol class="cases">
    <li><span class="case">One company’s network fails</span><span>{one_company_case} Only one company sees it, so it is not down. If one company’s probe is down altogether, its rounds are set aside, and with fewer than {companies} reporting the state is <span class="outcome">not enough data</span>.</span></li>
    {reference_case}
    <li><span class="case">A status page reports an incident</span><span>AWS posts an incident, but the counted networks’ calls keep succeeding. With no measured failure there is <span class="outcome">no outage</span>.</span></li>
    <li><span class="case">Crowd reports spike</span><span>Reports of problems rise on public sites, but the counted networks’ calls keep succeeding. Reports are not measurements, so <span class="outcome">no outage</span> is called.</span></li>
  </ol>
  {ver}
</section>

<section class="sec" id="why-clocks-differ">
  <h2>Why clocks differ</h2>
  <p>A provider’s status page starts its clock when an incident is posted and stops it when the incident is marked resolved, after the provider’s own checks. Crowd reports start when enough people notice and say so. Outside measurement starts when calls from outside fail under a stated rule.</p>
  <p>The three can disagree on both the start and the end, sometimes by a long way, and a policy with a waiting period turns on exactly those times. These rules are written down so anyone can see how this clock is read.</p>
</section>

<section class="sec" id="scope">
  <h2>Current scope</h2>
  <p class="intro">What the index covers today. Coverage is kept apart from the rules above and stated with dates.</p>
  <dl class="terms">
    <div><dt>Region</dt><dd>AWS {region}</dd></div>
    <div><dt>Services</dt><dd>{join_words(services)}</dd></div>
    <div><dt>Counted companies</dt><dd>{escape(join_words(counted_companies))}</dd></div>
  </dl>
  <h3>Probe networks</h3>
  <table class="stack">
    <thead><tr><th class="term" scope="col">Network</th><th scope="col">Company</th><th scope="col">Counted</th><th class="num" scope="col">Data since</th></tr></thead>
    <tbody>{"".join(scope_rows)}</tbody>
  </table>
</section>

<section class="sec" id="public-keys">
  <h2>Public keys</h2>
  <p class="intro">Public key of each probe network, Ed25519, base64.</p>
  <table class="stack">
    <thead><tr><th class="term" scope="col">Network</th><th scope="col">Public key</th></tr></thead>
    <tbody>{"".join(key_rows)}</tbody>
  </table>
  <p class="sec-foot">The Certificate key will be published here.</p>
</section>

<section class="sec" id="change-log">
  <h2>Change log</h2>
  <dl class="log">{log}</dl>
</section>

</main>
</div>
</div>

<footer class="foot">
  <div class="wrap">
    <span>© 2026 Nimbus Index</span>
    <a href="/methodology/">Methodology</a>
    <span class="disclaimer">Nothing on this site is an offer of insurance. Nimbus Index provides data only.</span>
  </div>
</footer>
</body>
</html>
"""


def build(root: Path = ROOT) -> str:
    try:
        rules = json.loads((root / "trigger_v1_rolling.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InputError(f"rules file: {e}")
    changelog = (root / "copy" / "methodology-changelog.md").read_text(encoding="utf-8")
    return render(rules, changelog, read_keys(root / "keys"))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed page is out of date")
    args = ap.parse_args(argv)
    try:
        html = build()
    except Exception as e:                  # any bad input: exit 2, never 1 (1 means drift)
        print(f"build_methodology: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != html:
            print(f"{OUT.relative_to(ROOT)} is out of date: run python3 scripts/build_methodology.py", file=sys.stderr)
            return 1
        print("Methodology page is up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
