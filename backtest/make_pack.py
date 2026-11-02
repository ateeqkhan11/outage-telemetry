"""Build the backtest pack (backtest/pack.html) from backtest/results.json. Run after backtest.py.

  python -m backtest.make_pack
"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = json.loads((ROOT / "backtest" / "results.json").read_text())
E = R["events"]
SVC = {"s3": "S3", "dynamodb": "DynamoDB", "lambda": "Lambda", "ec2": "EC2 API", "sts": "STS"}
NOT_SEEN_WHY = {
    "2012-12-24": "Elastic Load Balancing control plane; none of our five checks use it",
    "2014-06-13": "SimpleDB, a legacy service we don't check",
    "2018-05-31": "Power loss in one availability zone (instances, not regional APIs)",
    "2019-08-31": "Power loss in one availability zone (instances and volumes)",
    "2021-12-22": "Power loss in one availability zone; launches there failed, regional APIs fine",
    "2024-07-30": "Kinesis and CloudWatch logs; Lambda hurt only functions that wait on logging",
    "2026-05-07": "Cooling failure in one availability zone; no AWS summary yet",
}
e = html.escape


def verdict(lo: float, hi: float) -> str:
    if lo >= 0.9 and hi >= 0.9:
        return '<span class="pill yes">Pays</span>'
    if lo <= 0.1 and hi <= 0.1:
        return '<span class="pill no">No</span>'
    return f'<span class="pill maybe">Depends · {round(min(lo, hi) * 100)}–{round(max(lo, hi) * 100)}%</span>'


def cell(ev, rule, wait):
    r = ev["results"]
    if not r:
        return '<span class="muted">not seen</span>'
    return verdict(r[f"{rule}/low"]["p_meets"][wait], r[f"{rule}/high"]["p_meets"][wait])


def when(ev):
    d = datetime.strptime(ev["id"][:10], "%Y-%m-%d")
    return d.strftime("%-d %b %Y")


def short(ev):
    t = ev["title"]
    return t.split(" (")[0] if len(t) > 70 else t


def hours(m):
    return f"{m / 60:.1f} h" if m and m < 600 else (f"{round(m / 60)} h" if m else "—")


seen = [x for x in E if x["results"]]
unseen = [x for x in E if not x["results"]]
regional_seen = [x for x in seen if x["scope"] == "regional"]
pays10 = [x for x in seen if x["results"]["rolling/low"]["p_meets"]["120"] >= 0.9]
first, last = min(int(x["id"][:4]) for x in E), 2026

# ---- timeline chart (SVG): one mark per event, seen vs not seen by our checks, area ~ duration ----
W, H, L, Rt = 760, 170, 170, 24
x = lambda d: L + (d - datetime(first, 1, 1)).days / (datetime(last + 1, 1, 1) - datetime(first, 1, 1)).days * (W - L - Rt)
lanes = {"seen": 58, "unseen": 122}
marks = []
for ev in E:
    d = datetime.strptime(ev["id"][:10], "%Y-%m-%d")
    dur = ev.get("duration_min") or 60
    r = min(20, 4 + 2.2 * math.sqrt(dur / 60))
    lane = "seen" if ev["results"] else "unseen"
    cls = "m-seen" if lane == "seen" else "m-unseen"
    tip = f"{when(ev)}: {short(ev)}, {hours(dur)}, {'seen' if lane == 'seen' else 'not seen'} by our checks"
    marks.append(f'<circle class="{cls}" cx="{x(d):.1f}" cy="{lanes[lane]}" r="{r:.1f}"><title>{e(tip)}</title></circle>')
ticks = "".join(f'<line class="grid" x1="{x(datetime(y,1,1)):.1f}" x2="{x(datetime(y,1,1)):.1f}" y1="30" y2="145"/>'
                f'<text class="tick" x="{x(datetime(y,1,1)):.1f}" y="162" text-anchor="middle">{y}</text>'
                for y in range(first, last + 1, 3))
chart = f'''<svg viewBox="0 0 {W} {H}" role="img" aria-label="Timeline of {len(E)} AWS us-east-1 outages from {first} to {last}: {len(seen)} would have been seen by our five checks, {len(unseen)} would not.">
  {ticks}
  <text class="lane" x="0" y="{lanes['seen'] + 4}">Seen by our checks</text>
  <text class="lane" x="0" y="{lanes['unseen'] + 4}">Not seen</text>
  {''.join(marks)}
</svg>'''

rows = []
for ev in E:
    hit = ", ".join(SVC[c["check"]] for c in ev["checks_impaired"]) or f'<span class="muted">{e(NOT_SEEN_WHY.get(ev["id"], "none of our checks"))}</span>'
    flag = ' <span class="tag">press only</span>' if ev.get("secondary_source_only") else ""
    rows.append(f'''<tr><td class="num nowrap">{when(ev)}</td><td>{e(short(ev))}{flag}</td>
      <td>{"Regional" if ev["scope"] == "regional" else "One zone"}</td><td class="num">{hours(ev.get("duration_min"))}</td><td>{hit}</td>
      <td>{cell(ev, "minute", "60")}</td><td>{cell(ev, "minute", "120")}</td><td>{cell(ev, "rolling", "60")}</td><td>{cell(ev, "rolling", "120")}</td></tr>''')

sens_rows = []
for ev in seen:
    tds = []
    for share in ("10%", "25%", "50%"):
        lo, hi = R["sensitivity"][f"{share}/low"][ev["id"]]["120"], R["sensitivity"][f"{share}/high"][ev["id"]]["120"]
        tds.append(f"<td>{verdict(lo, hi)}</td>")
    sens_rows.append(f'<tr><td class="num nowrap">{when(ev)}</td><td>{e(short(ev))}</td>{"".join(tds)}</tr>')
sens_counts = {s: sum(1 for ev in seen if min(R["sensitivity"][f"{s}/low"][ev["id"]]["120"], R["sensitivity"][f"{s}/high"][ev["id"]]["120"]) >= 0.9)
               for s in ("10%", "25%", "50%")}

fp_rows = "".join(f'<tr><td>{e(k)}</td><td class="num">{v["minute"]} min</td><td class="num">{v["rolling"]} min</td>'
                  f'<td>{"<span class=pill yes>Correct</span>" if (("control" in k) == (v["rolling"] >= 120)) else "<span class=pill no>Wrong</span>"}</td></tr>'
                  for k, v in R["false_positives"].items())
srcs = sorted({s for ev in E for s in ev.get("sources", [])})

page = f'''<meta charset="utf-8">
<title>us-east-1 Outage Backtest</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column for the argument, full-width tables for the evidence */
:root {{
  --bg: #F5F6F7; --paper: #FFFFFF; --ink: #121A22; --muted: #5A6570; --line: #D8DDE2; --grid: #E6E9EC;
  --seen: #1F5FA8; --unseen: #9AA5B1; --yes: #1D6B45; --yes-bg: #E2F1E8; --no: #6B7480; --no-bg: #EEF0F2;
  --maybe: #8A5A00; --maybe-bg: #FBF0D9; --accent: #1F5FA8;
  --display: 'IBM Plex Sans Condensed', 'Arial Narrow', Arial, sans-serif;
  --body: 'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif;
  --mono: 'IBM Plex Mono', ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #0F151B; --paper: #161E26; --ink: #E3E8ED; --muted: #98A4B0; --line: #2A3540; --grid: #222C36;
  --seen: #6FA8E8; --unseen: #5E6A76; --yes: #7FD3A4; --yes-bg: #173326; --no: #A0AAB4; --no-bg: #222A33;
  --maybe: #E8B65A; --maybe-bg: #33280F; --accent: #6FA8E8; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #0F151B; --paper: #161E26; --ink: #E3E8ED; --muted: #98A4B0; --line: #2A3540; --grid: #222C36;
  --seen: #6FA8E8; --unseen: #5E6A76; --yes: #7FD3A4; --yes-bg: #173326; --no: #A0AAB4; --no-bg: #222A33;
  --maybe: #E8B65A; --maybe-bg: #33280F; --accent: #6FA8E8; color-scheme: dark }}
body {{ background: var(--bg); color: var(--ink); font: 15.5px/1.6 var(--body); padding-inline: 16px; padding-block: 40px 64px; }}
.page {{ max-width: 1000px; margin: 0 auto; display: flex; flex-direction: column; gap: 36px; }}
.prose {{ max-width: 70ch; }}
h1, h2 {{ font-family: var(--display); font-weight: 600; margin: 0; line-height: 1.15; text-wrap: balance; letter-spacing: -0.005em; }}
h1 {{ font-size: clamp(30px, 5vw, 44px); }} h2 {{ font-size: 25px; margin-bottom: 10px; }}
p {{ margin: 0 0 12px; }} ul {{ margin: 0 0 12px; padding-left: 22px; }} li {{ margin-bottom: 6px; }}
a {{ color: var(--accent); }} .muted {{ color: var(--muted); }}
.meta {{ color: var(--muted); font-size: 14px; margin-top: 10px; }}
.num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 0.92em; }} .nowrap {{ white-space: nowrap; }}
.stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 20px; }}
.stat {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-width: 0; }}
.stat b {{ display: block; font: 600 30px var(--display); }} .stat span {{ font-size: 13.5px; color: var(--muted); }}
.figure {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 16px; overflow-x: auto; }}
.figure svg {{ width: 100%; min-width: 600px; height: auto; display: block; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }} .tick {{ fill: var(--muted); font: 12px var(--mono); }} .lane {{ fill: var(--ink); font: 500 13px var(--body); }}
.m-seen {{ fill: var(--seen); fill-opacity: .85; stroke: var(--paper); stroke-width: 2; }}
.m-unseen {{ fill: none; stroke: var(--unseen); stroke-width: 2; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: var(--muted); margin-top: 8px; }}
.legend i {{ display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }}
.tablewrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; background: var(--paper); }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; min-width: 760px; }}
th, td {{ text-align: left; vertical-align: top; padding: 9px 12px; border-bottom: 1px solid var(--line); }}
th {{ font-size: 12px; font-weight: 600; color: var(--muted); letter-spacing: .04em; text-transform: uppercase; background: var(--bg); }}
th.grp {{ text-align: center; border-left: 1px solid var(--line); }} td.l, th.l {{ border-left: 1px solid var(--line); }}
tr:last-child td {{ border-bottom: 0; }}
.pill {{ display: inline-block; font-size: 12.5px; font-weight: 600; padding: 1px 9px; border-radius: 99px; white-space: nowrap; }}
.pill.yes {{ background: var(--yes-bg); color: var(--yes); }} .pill.no {{ background: var(--no-bg); color: var(--no); }} .pill.maybe {{ background: var(--maybe-bg); color: var(--maybe); }}
.tag {{ font-size: 11.5px; color: var(--muted); border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; white-space: nowrap; }}
.callout {{ background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 16px 18px; }}
.sources ol {{ font-size: 13px; color: var(--muted); }} .sources li {{ word-break: break-all; }}
footer {{ color: var(--muted); font-size: 13px; border-top: 1px solid var(--line); padding-top: 16px; }}
@media (max-width: 720px) {{ .stats {{ grid-template-columns: 1fr 1fr; }} }}
</style>
<div class="page">
<header>
  <h1>How an independent outage trigger would have handled {len(E)} AWS us-east-1 outages</h1>
  <p class="meta">Backtest pack · draft for review · built {datetime.now().strftime("%-d %B %Y")} · AWS us-east-1 (N. Virginia), {first}–{last}</p>
  <p class="prose" style="margin-top:14px">We replayed every us-east-1 outage AWS has published a post-event summary for, plus four widely reported ones without a summary, against our draft trigger. The trigger needs probes run by two independent operators to see the same AWS service failing. The question for each outage: would it have paid after a 1-hour or a 2-hour waiting period?</p>
  <div class="stats">
    <div class="stat"><b>{len(E)}</b><span>outages, {first}–{last}</span></div>
    <div class="stat"><b>{len(seen)}</b><span>visible to our five core checks</span></div>
    <div class="stat"><b>{len(pays10)}</b><span>would pay after 2 hours with the recommended rule</span></div>
    <div class="stat"><b>0</b><span>false triggers in our must-not-pay tests</span></div>
  </div>
</header>

<section>
  <h2>Every outage since {first}</h2>
  <div class="figure">{chart}
    <div class="legend"><span><i style="background:var(--seen)"></i>Seen by our five checks (S3, DynamoDB, Lambda, EC2 API, STS)</span><span><i style="border:2px solid var(--unseen)"></i>Not seen</span><span>Circle size grows with the outage's length (capped for the longest)</span></div></div>
</section>

<section>
  <h2>What we found</h2>
  <div class="prose">
    <ul>
      <li><b>Clear, total outages pay under any rule.</b> The 2017 S3 outage and the October 2025 DynamoDB failure would have paid after both waiting periods in every simulation.</li>
      <li><b>Most outages are partial, and a simple per-minute rule misses them.</b> Some calls keep working. Checked once a minute, a partial outage looks like flickering and rarely adds up to an hour. That affects the 2015, 2020, 2021 and 2023 events.</li>
      <li><b>Six checks a minute, judged over a rolling 10 minutes, catches them.</b> With that rule, every outage our checks can see that lasted over 2 hours pays, in every simulation. This is our recommendation for trigger v1.</li>
      <li><b>{len(unseen)} of {len(E)} outages wouldn't be seen.</b> {sum(1 for x in unseen if x["scope"] != "regional")} were confined to one availability zone, and {sum(1 for x in unseen if x["scope"] == "regional")} hit services outside our five checks (ELB, SimpleDB, Kinesis/CloudWatch). This is the basis risk to discuss with buyers. Adding checks for those services and zones is cheap, and it's the Q1 plan.</li>
      <li><b>Zone outages can still show up.</b> In 2011 and October 2012 one zone's failure also degraded the region-wide EC2 API, which our check measures, so those pay too.</li>
      <li><b>Frequency.</b> With the recommended rule and a 2-hour wait, about {len([x for x in pays10 if x["scope"] == "regional"])} regional events in {last - first + 1} years would have paid, {len([x for x in pays10 if x["scope"] == "regional" and int(x["id"][:4]) >= 2020])} of them since 2020.</li>
    </ul>
  </div>
</section>

<section>
  <h2>Event by event</h2>
  <div class="tablewrap"><table>
    <tr><th rowspan="2">Date</th><th rowspan="2">What happened</th><th rowspan="2">Scope</th><th rowspan="2">Length</th><th rowspan="2">Our checks that fail</th>
      <th class="grp" colspan="2">Draft rule · 1 check/min</th><th class="grp" colspan="2">Recommended · 6 checks/min, rolling</th></tr>
    <tr><th class="l">1 h wait</th><th>2 h wait</th><th class="l">1 h wait</th><th>2 h wait</th></tr>
    {''.join(rows)}
  </table></div>
  <p class="muted" style="font-size:13.5px;margin-top:10px">"Pays" means the trigger fired in at least 90% of {R["runs"]} simulations, under both the low and the high failure-rate assumption. "Depends" shows the range. Length is AWS's overall impact window; our checks may be affected for less of it.</p>
</section>

<section>
  <h2>The threshold is a pricing dial</h2>
  <p class="prose">The recommended rule counts an operator as seeing a failure when a set share of its checks over 10 minutes fail. A lower threshold pays on milder partial outages and costs more to cover. With a 2-hour wait: {sens_counts["10%"]} events pay at 10%, {sens_counts["25%"]} at 25% under both assumptions, and {sens_counts["50%"]} at 50%.</p>
  <div class="tablewrap"><table>
    <tr><th>Date</th><th>What happened</th><th>10% of checks fail</th><th>25%</th><th>50%</th></tr>
    {''.join(sens_rows)}
  </table></div>
</section>

<section>
  <h2>Must-not-pay tests</h2>
  <p class="prose">An independent trigger has to ignore problems that aren't AWS's. Each case below ran for 3 hours through the same detection code.</p>
  <div class="tablewrap"><table style="min-width:600px">
    <tr><th>Situation</th><th>Draft rule</th><th>Recommended</th><th>Result</th></tr>
    {fp_rows}
  </table></div>
  <p class="muted" style="font-size:13.5px;margin-top:10px">Numbers are the longest outage each rule reported. GitHub Actions runs on Microsoft Azure, so GitHub and Azure probes count as one operator. A failed control check (a site outside AWS) marks the probe as down rather than AWS. An HTTP 403 means AWS answered, so it never counts as an outage.</p>
</section>

<section class="callout prose">
  <h2>How this was done, and its limits</h2>
  <ul>
    <li><b>Sources.</b> AWS's own post-event summaries for {sum(1 for x in E if not x.get("secondary_source_only"))} events. Press and status-page reports for the {sum(1 for x in E if x.get("secondary_source_only"))} marked "press only".</li>
    <li><b>Simulated probes.</b> Our probes didn't exist during these events, and AWS publishes service-level descriptions, not per-call error rates. So we simulated three independent probe operators minute by minute, and ran their results through the same detection code the live probes use.</li>
    <li><b>Assumed failure rates per call:</b>
      <ul>
        <li>"Largely unavailable": 95%.</li>
        <li>"Very high errors": 55%.</li>
        <li>"Elevated errors" (partial): tested at both 20% and 50%.</li>
        <li>Latency-only: 5% or 20%.</li>
      </ul>
    </li>
    <li><b>What we assumed about the probes.</b> One network misses 15% of minutes, to reflect GitHub's late schedules. Background failures run at 0.05% of calls.</li>
    <li><b>Judgement calls are written down in the code.</b> For example, the 2017 Lambda impact is assumed to share S3's window. The 2021 STS impairment is treated as latency only. The 2024 Lambda impact doesn't count, because only functions that wait on logging were hurt.</li>
    <li><b>Durations from the rolling rule</b> can run a few minutes past the real end of an outage, because it looks back 10 minutes.</li>
    <li><b>Reproduce it:</b> <span class="num">python -m backtest.backtest</span> in the outage-telemetry repository.</li>
  </ul>
</section>

<section class="sources">
  <h2>Sources</h2>
  <ol>{''.join(f'<li><a href="{e(s)}">{e(s)}</a></li>' for s in srcs)}</ol>
</section>
<footer>Draft for review, not an offer of cover. Outage windows come from AWS post-event summaries and press reports. Per-call failure rates are assumptions, stated above.</footer>
</div>
'''
(ROOT / "backtest" / "pack.html").write_text(page)
print(f"wrote backtest/pack.html: {len(E)} events, {len(seen)} seen, {len(pays10)} pay at 2h (recommended)")
