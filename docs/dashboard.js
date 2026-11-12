// Shared by the public dashboard (docs/index.html) and the Nimbus Index app, which sets data-src on the script tag.
(function () {
  const SRC = (document.currentScript && document.currentScript.dataset.src) || new URLSearchParams(location.search).get("src") ||
    "https://raw.githubusercontent.com/ateeqkhan11/outage-telemetry/data/status/latest.json";
  const $ = (id) => document.getElementById(id);
  const NAMES = { s3: ["S3", "GetObject"], dynamodb: ["DynamoDB", "GetItem"], lambda: ["Lambda", "Invoke"], ec2: ["EC2 API", "DescribeInstances"], sts: ["STS", "GetCallerIdentity"] };
  const WORD = { up: "Up", down: "Outage", unknown: "Not decidable yet" };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const ago = (iso) => { const m = Math.round((Date.now() - Date.parse(iso)) / 60000); return m < 1 ? "just now" : m < 90 ? `${m} min ago` : `${Math.round(m / 60)} h ago`; };
  const pill = (st, text) => `<span class="pill s-${st}">${esc(text || WORD[st])}</span>`;

  function render(s) {
    $("updated").textContent = `Updated ${ago(s.generated_at)} (${s.generated_at.replace("T", " ").slice(0, 16)} UTC) · last probe minute ${s.last_minute ? s.last_minute.replace("T", " ").replace("Z", " UTC") : "none"}`;
    // what the probes see right now: failed calls in the last hour, all networks
    const lastHour = (v) => v.timeline.slice(-6).reduce((a, b) => [a[0] + b.failed, a[1] + b.checks], [0, 0]);
    const raw = Object.values(s.services).map(lastHour);
    const rawFailed = raw.reduce((a, r) => a + r[0], 0), rawChecks = raw.reduce((a, r) => a + r[1], 0);
    const ov = $("overall");
    if (s.can_decide) {
      ov.className = `pill big s-${s.overall}`;
      ov.textContent = s.overall === "up" ? "All services up" : s.overall === "down" ? "Outage detected" : "Waiting for data";
    } else {
      ov.className = `pill big s-${rawFailed ? "unknown" : "up"}`;
      ov.textContent = rawChecks ? (rawFailed ? `${rawFailed} failed calls in the last hour` : "All checks passing") : "Waiting for data";
    }

    const n = $("notice");
    if (!s.can_decide) {
      n.hidden = false;
      n.innerHTML = `${pill("up", "Live")}<div><b>Measuring every minute; official outage calls start when the second independent network goes live</b>
        An outage is only called when probes run by ${s.rules.operators_required} different companies see the same failure, so no single provider's glitch can trigger a payout.
        Live and counted now: ${s.independent_operators.length} (${esc(s.independent_operators.join(", ") || "none")}). Second network by 13 November. Every call is already measured and signed below.</div>`;
    } else {
      n.hidden = false;
      n.innerHTML = `${pill("up", "Official")}<div><b>${s.independent_operators.length} independent operators counted: ${esc(s.independent_operators.length > 2 ? s.independent_operators.slice(0, -1).join(", ") + " and " + s.independent_operators.slice(-1) : s.independent_operators.join(" and "))}</b>
        A service is called down when probes run by ${s.rules.operators_required} different companies see it failing (${Math.round(s.rules.window_fail_share * 100)}% or more of calls over ${s.rules.window_minutes} minutes) while their own connection works. Every call is signed and can be checked below.</div>`;
    }

    $("services").innerHTML = Object.entries(s.services).map(([k, v]) => {
      const [name, op] = NAMES[k] || [k, ""];
      const okShare = v.checks ? (100 * (v.checks - v.failed) / v.checks) : null;
      const lat = Object.entries(v.latency_ms_p50_last_hour).map(([net, ms]) => `${esc(net)} ${ms} ms`).join(" · ") || "—";
      const bars = v.timeline.map((b) => {
        if (!b.checks) return `<i class="none" title="${esc(b.t)}: no data"></i>`;
        const share = b.failed / b.checks;
        return share > 0 ? `<i class="bad" style="height:${Math.max(18, share * 100)}%" title="${esc(b.t)}: ${b.failed} of ${b.checks} calls failed"></i>`
                         : `<i style="height:100%" title="${esc(b.t)}: all ${b.checks} calls OK"></i>`;
      }).join("");
      const [hf, hn] = lastHour(v);
      const badge = s.can_decide ? pill(v.state) : (hn ? (hf ? pill("unknown", `${hf} failed, last hour`) : pill("up", "Responding")) : pill("unknown", "No data"));
      return `<article class="svc"><div class="svc-head"><div><h3>${name}</h3><small>${op}</small></div>${badge}</div>
        <div class="tl" role="img" aria-label="${name}: failed calls over the last 24 hours">${bars}</div>
        <div class="tl-axis"><span>24 h ago</span><span>now</span></div>
        <dl class="kv"><dt>Calls OK, 24 h</dt><dd class="num">${okShare === null ? "—" : okShare.toFixed(okShare === 100 ? 0 : 2) + "%"} <span class="muted">of ${v.checks.toLocaleString()}</span></dd>
          <dt>Official uptime</dt><dd class="num">${v.uptime_pct === null ? "from 2nd network" : v.uptime_pct.toFixed(3) + "%"}</dd>
          <dt>Median latency, last hour</dt><dd class="num">${lat}</dd></dl>
        ${v.last_error ? `<div class="err">Last error: ${esc(v.last_error)}</div>` : ""}</article>`;
    }).join("");

    $("outages").innerHTML = s.outages.length
      ? `<div class="tablewrap"><table><tr><th>Start</th><th>End</th><th>Length</th><th>Services</th>${s.rules.waiting_periods_min.map((w) => `<th>${w / 60} h wait met</th>`).join("")}</tr>
         ${s.outages.map((o) => `<tr><td class="num">${esc(o.start)}</td><td class="num">${o.ongoing ? "ongoing" : esc(o.end)}</td><td class="num">${o.duration_min} min</td><td>${esc(o.services.join(", "))}</td>
           ${s.rules.waiting_periods_min.map((w) => `<td>${o.meets_waiting_period[w] ? '<span class="bad">Yes</span>' : "No"}</td>`).join("")}</tr>`).join("")}</table></div>`
      : `<p style="margin:0">${s.can_decide ? "None. No service failed for two independent operators at once." : "None can be called yet: this needs a second independent operator. Raw failures, if any, show as red bars above."}</p>`;

    const rows = Object.entries(s.networks).map(([net, v]) => `<tr><td><b>${esc(net)}</b><br><span class="muted" style="font-size:12.5px">${esc(v.host || "")}</span></td>
      <td>${esc(v.operator)}</td><td>${v.counted ? "Yes" : "No"}</td><td class="num">${v.last_minute ? ago(v.last_minute) : "—"}</td>
      <td class="num">${(100 * v.minutes_covered / v.minutes_in_window).toFixed(1)}%</td><td class="num">${v.longest_gap_min} min</td>
      <td>${v.chain_valid ? '<span class="ok">Valid</span>' : `<span class="bad">Invalid</span> <span class="err">${esc(v.problems[0] || "")}</span>`}</td></tr>`).join("");
    $("networks").insertAdjacentHTML("beforeend", rows);

    const net = Object.keys(s.sample_records).find((k) => s.networks[k] && s.networks[k].counted) || Object.keys(s.sample_records)[0];
    if (net) {
      const rec = s.sample_records[net][s.sample_records[net].length - 1];
      $("record").textContent = JSON.stringify(rec, null, 1);
      $("pubkey").textContent = `${net}: ${s.public_keys[net] || "missing"}`;
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
    const step = (ok, text) => `<li><span class="${ok ? "pass" : "fail"}">${ok ? "Pass" : "Fail"}</span> ${text}</li>`;
    let html = "";
    try {
      const digest = hex(await crypto.subtle.digest("SHA-256", canonical(rec)));
      html += step(digest === rec.hash, `SHA-256 of the record's content is <span class="num">${digest.slice(0, 16)}…</span>, ${digest === rec.hash ? "matching" : "NOT matching"} its <span class="num">hash</span> field.`);
      const key = await crypto.subtle.importKey("raw", fromB64(pubB64), { name: "Ed25519" }, false, ["verify"]);
      const ok = await crypto.subtle.verify({ name: "Ed25519" }, key, fromB64(rec.sig), fromHex(rec.hash));
      html += step(ok, `Ed25519 signature ${ok ? "is valid" : "is NOT valid"} for the <b>${esc(net)}</b> network's public key.`);
      html += `<li class="muted">Record ${rec.seq} links to the one before it through <span class="num">prev = ${esc(rec.prev.slice(0, 16))}…</span>; the full chain is checked on every update (see Signatures above).</li>`;
    } catch (e) {
      html += step(false, `Your browser couldn't run the check (${esc(e.message)}). Ed25519 needs a recent Chrome, Edge, Firefox or Safari; or run <span class="num">python -m probe.verify</span> from the repo.`);
    }
    out.innerHTML = html;
  }

  fetch(SRC, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(render)
    .catch((e) => { $("updated").textContent = `Couldn't load the latest results (${e.message}). The raw data is on the data branch.`; $("overall").textContent = "Unavailable"; });
})();
