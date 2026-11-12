// Shared by the public dashboard (docs/index.html) and the Nimbus Index app, which sets data-src on the script tag.
// Renders: the title band (state, who judged), the services board, the trigger ladder, probe networks, and the
// in-browser check of a signed record.
(function () {
  const SRC = (document.currentScript && document.currentScript.dataset.src) || new URLSearchParams(location.search).get("src") ||
    "https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/data/status/latest.json";
  const $ = (id) => document.getElementById(id);
  const NAMES = { s3: ["S3", "GetObject"], dynamodb: ["DynamoDB", "GetItem"], lambda: ["Lambda", "Invoke"], ec2: ["EC2 API", "DescribeInstances"], sts: ["STS", "GetCallerIdentity"] };
  const COMPANY = { microsoft: "Microsoft", cloudflare: "Cloudflare", google: "Google", aws: "AWS", "independent-vps": "Independent VPS" };
  const WORD = { up: "Up", down: "Outage", unknown: "Undecided" };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const ago = (iso) => { const m = Math.round((Date.now() - Date.parse(iso)) / 60000); return m < 1 ? "just now" : m < 90 ? `${m} min ago` : `${Math.round(m / 60)} h ago`; };
  const pill = (st, text) => `<span class="pill s-${st}">${esc(text || WORD[st])}</span>`;
  const company = (op) => COMPANY[op] || op;
  const listed = (a) => a.length > 2 ? a.slice(0, -1).join(", ") + " and " + a[a.length - 1] : a.join(" and ");
  const dur = (m) => { const h = Math.floor(m / 60), r = m % 60; return h && r ? `${h} h ${r} min` : h ? `${h} h` : `${r} min`; };
  const hm = (iso) => iso.slice(11, 16);
  const day = (iso) => new Date(iso.slice(0, 10) + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const CHECK = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.4 5 8.8l4.6-5.6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const SEAL = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.2 9.6 2.6l2.1-.2.6 2 1.8 1.1-.7 2 .7 2-1.8 1.1-.6 2-2.1-.2L8 14.8l-1.6-1.4-2.1.2-.6-2L1.9 10.5l.7-2-.7-2 1.8-1.1.6-2 2.1.2Z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="m5.4 8.1 1.8 1.8 3.4-3.7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // the trigger ladder, also drawn server-side by the app's History and Reports pages (same markup and classes)
  function ladder(outages, waits, emptyText) {
    if (!outages.length) return `<p class="ladder-empty">${esc(emptyText)}</p>`;
    const longest = Math.max(...outages.map((o) => o.duration_min), ...waits);
    const scale = Math.ceil((longest * 1.08) / 60) * 60;
    const pct = (m) => `${(100 * m / scale).toFixed(2)}%`;
    const ticks = [];
    for (let m = 0; m <= scale; m += 60) ticks.push(`<span style="left:${pct(m)}" class="${waits.includes(m) ? "att" : ""}">${m ? `${m / 60} h` : "0"}${waits.includes(m) ? "<em class=\"w\" style=\"font-style:normal\"> wait</em>" : ""}</span>`);
    const rows = outages.slice().reverse().map((o, i) => {
      const met = waits.map((w) => `<span class="met ${o.meets_waiting_period[w] ? "yes" : ""}">${o.meets_waiting_period[w] ? CHECK : ""}${w / 60} h ${o.meets_waiting_period[w] ? "met" : "not met"}</span>`).join("");
      return `<div class="ladder-row"><div class="lr-when"><b>${day(o.start)}</b><span>${hm(o.start)}–${o.ongoing ? "ongoing" : hm(o.end)} UTC</span></div>
        <div class="lr-track" role="img" aria-label="${dur(o.duration_min)}"><span class="lr-bar ${o.ongoing ? "ongoing" : ""}" style="--w:${pct(o.duration_min)};--i:${i}"></span>
          ${waits.map((w) => `<span class="lr-att" style="left:${pct(w)}"></span>`).join("")}</div>
        <div class="lr-dur">${dur(o.duration_min)}</div>
        <div class="lr-meta">${esc(o.services.map((s) => (NAMES[s] || [s])[0]).join(", "))} ${met}</div></div>`;
    }).join("");
    return `<div class="ladder"><div class="ladder-scale" aria-hidden="true"><span>Outage</span><div class="ticks">${ticks.join("")}</div><span style="text-align:right">Length</span></div>${rows}</div>`;
  }
  window.NimbusLadder = ladder;

  function render(s) {
    const nets = Object.entries(s.networks);
    const valid = nets.every(([, v]) => v.chain_valid);
    $("updated").textContent = `Updated ${ago(s.generated_at)} · last probe minute ${s.last_minute ? s.last_minute.slice(11, 16) + " UTC" : "none"} · AWS us-east-1`;
    const lastHour = (v) => v.timeline.slice(-6).reduce((a, b) => [a[0] + b.failed, a[1] + b.checks], [0, 0]);
    const raw = Object.values(s.services).map(lastHour);
    const rawFailed = raw.reduce((a, r) => a + r[0], 0), rawChecks = raw.reduce((a, r) => a + r[1], 0);
    const down = Object.entries(s.services).filter(([, v]) => v.state === "down").map(([k]) => (NAMES[k] || [k])[0]);
    let title, st;
    if (s.can_decide) {
      st = s.overall;
      title = s.overall === "up" ? "All five services up" : s.overall === "down" ? `Outage: ${listed(down)}` : "Waiting for data";
    } else {
      st = rawFailed ? "unknown" : "up";
      title = rawChecks ? (rawFailed ? `${rawFailed} failed calls in the last hour` : "All checks passing") : "Waiting for data";
    }
    $("state-title").textContent = title;
    $("state-title").className = `state-title st-${st}`;
    const ov = $("overall");
    ov.className = `pill big s-${st}`;
    ov.textContent = s.can_decide ? (st === "up" ? "Official: up" : st === "down" ? "Official: outage" : "Official: undecided") : "Not official yet";

    const counted = nets.filter(([, v]) => v.counted), ref = nets.filter(([, v]) => !v.counted);
    $("judges").innerHTML = `<ul>${counted.map(([n, v]) => `<li>${esc(company(v.operator))} <small>${esc(n)} probes</small></li>`).join("")}
      ${ref.map(([n]) => `<li class="ref">AWS reference <small>${esc(n)}, shown, never counted</small></li>`).join("")}</ul>
      <span class="seal ${valid ? "" : "bad"}">${SEAL}${valid ? `Signed · ${nets.length} chains valid` : "A chain failed its check"}</span>`;
    $("judges-note").textContent = s.can_decide
      ? `Down only when ${s.rules.operators_required} of these companies see it fail: ${Math.round(s.rules.window_fail_share * 100)}% of calls over ${s.rules.window_minutes} min.`
      : `Official calls need ${s.rules.operators_required} independent companies; ${s.independent_operators.length} live now.`;

    $("services").innerHTML = Object.entries(s.services).map(([k, v]) => {
      const [name, op] = NAMES[k] || [k, ""];
      const okShare = v.checks ? (100 * (v.checks - v.failed) / v.checks) : null;
      const bars = v.timeline.map((b) => {
        if (!b.checks) return `<i class="none" title="${esc(b.t)}: no data"></i>`;
        const share = b.failed / b.checks;
        return share > 0 ? `<i class="bad" style="height:${Math.max(18, share * 100)}%" title="${esc(b.t)}: ${b.failed} of ${b.checks} calls failed"></i>`
                         : `<i title="${esc(b.t)}: all ${b.checks} calls OK"></i>`;
      }).join("");
      const [hf, hn] = lastHour(v);
      const badge = s.can_decide ? pill(v.state) : (hn ? (hf ? pill("unknown", `${hf} failed, last hour`) : pill("up", "Responding")) : pill("unknown", "No data"));
      const lat = Object.entries(v.latency_ms_p50_last_hour).map(([net, ms]) => `${esc(net)} <b class="num">${ms} ms</b>`).join(" · ") || "—";
      return `<tr><td><span class="svc-name">${name}</span><span class="cell-sub">${op}</span></td><td>${badge}</td>
        <td><div class="tl" role="img" aria-label="${name}: failed calls over the last 24 hours">${bars}</div><div class="tl-axis"><span>24 h ago</span><span>now</span></div>
          ${v.last_error ? `<div class="err">Last error: ${esc(v.last_error)}</div>` : ""}</td>
        <td class="num"><b>${okShare === null ? "—" : okShare.toFixed(okShare === 100 ? 0 : 2) + "%"}</b><span class="cell-sub">of ${v.checks.toLocaleString()} calls</span>
          <span class="cell-sub">${v.uptime_pct === null ? "official from 2nd company" : `official ${v.uptime_pct.toFixed(3)}%`}</span></td>
        <td><div class="lat">${lat}</div></td></tr>`;
    }).join("");

    $("outages").innerHTML = ladder(s.outages, s.rules.waiting_periods_min,
      s.can_decide ? "No outage called in the last 24 hours: no service failed for two independent companies at once."
                   : "None can be called yet: this needs a second independent company. Raw failures show as red bars above.");

    $("networks").innerHTML = nets.map(([net, v]) => `<tr><td><b>${esc(net)}</b><span class="cell-sub">${esc(v.host || "")}</span></td>
      <td data-label="Company">${esc(v.counted ? company(v.operator) : "AWS (reference)")}</td><td data-label="Counted">${v.counted ? "Yes" : "No, inside AWS"}</td><td class="num" data-label="Last result">${v.last_minute ? ago(v.last_minute) : "—"}</td>
      <td class="num" data-label="Coverage, 24 h">${(100 * v.minutes_covered / v.minutes_in_window).toFixed(1)}%</td><td class="num" data-label="Longest gap">${v.longest_gap_min} min</td>
      <td data-label="Signatures">${v.chain_valid ? '<span class="ok">Valid</span>' : `<span class="bad">Invalid</span> <span class="err">${esc(v.problems[0] || "")}</span>`}</td></tr>`).join("");

    const net = Object.keys(s.sample_records).find((k) => s.networks[k] && s.networks[k].counted) || Object.keys(s.sample_records)[0];
    if (net) {
      const rec = s.sample_records[net][s.sample_records[net].length - 1];
      $("record").textContent = JSON.stringify(rec, null, 1);
      $("pubkey").textContent = `${net}: ${s.public_keys[net] || "missing"}`;
      $("record-from").textContent = `${company(s.networks[net].operator)} · ${net} · record ${rec.seq}`;
      const btn = $("verify-btn");
      btn.disabled = false;
      btn.onclick = () => verifyRecord(rec, s.public_keys[net], net);
    }
  }

  // ---- in-browser verification: identical canonical JSON to probe/chain.py and workers/src/chain.js ----
  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const fromHex = (h) => new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));
  const fromB64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  function canonical(rec) {
    const keys = Object.keys(rec).filter((k) => k !== "hash" && k !== "sig").sort();
    return new TextEncoder().encode("{" + keys.map((k) => JSON.stringify(k) + ":" + JSON.stringify(rec[k])).join(",") + "}");
  }
  async function verifyRecord(rec, pubB64, net) {
    const out = $("verify-steps");
    out.hidden = false;
    const step = (ok, text) => `<li><span class="${ok ? "pass" : "fail"}">${ok ? "Pass" : "Fail"}</span><span>${text}</span></li>`;
    let html = "";
    try {
      const digest = hex(await crypto.subtle.digest("SHA-256", canonical(rec)));
      html += step(digest === rec.hash, `SHA-256 of the record's content is <span class="mono">${digest.slice(0, 16)}…</span>, ${digest === rec.hash ? "matching" : "NOT matching"} its <span class="mono">hash</span> field.`);
      const key = await crypto.subtle.importKey("raw", fromB64(pubB64), { name: "Ed25519" }, false, ["verify"]);
      const ok = await crypto.subtle.verify({ name: "Ed25519" }, key, fromB64(rec.sig), fromHex(rec.hash));
      html += step(ok, `Ed25519 signature ${ok ? "is valid" : "is NOT valid"} for the <b>${esc(net)}</b> network's public key.`);
      html += `<li class="muted">Record ${rec.seq} links to the one before it through <span class="mono">prev = ${esc(rec.prev.slice(0, 16))}…</span>; every chain is checked in full on each update (Signatures, below).</li>`;
    } catch (e) {
      html += step(false, `Your browser couldn't run the check (${esc(e.message)}). Ed25519 needs a recent Chrome, Edge, Firefox or Safari; or run <span class="mono">python -m probe.verify</span> from the repo.`);
    }
    out.innerHTML = html;
  }

  if (!$("state-title")) return;                       // pages that only borrow the ladder
  fetch(SRC, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(render)
    .catch((e) => { $("updated").textContent = `Couldn't load the latest results (${e.message}). The raw data is on the data branch.`; $("overall").textContent = "Unavailable"; $("state-title").textContent = "Status unavailable"; });
})();
