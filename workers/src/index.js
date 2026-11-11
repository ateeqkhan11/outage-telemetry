// Cloudflare Worker probe: every minute (cron), run the control check and the 5 AWS us-east-1 checks, seal the
// results onto the "cloudflare" chain and save them in D1 (see below).
// Secrets (wrangler secret put ...): AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, PROBE_SIGNING_KEY.
// Vars (wrangler.toml): PROBE_BUCKET, PROBE_OBJECT_KEY, PROBE_TABLE, PROBE_TABLE_KEY, PROBE_FUNCTION, CONTROL_URL.
import { AwsClient } from "aws4fetch";
import { GENESIS, loadPrivate, seal } from "./chain.js";

const REGION = "us-east-1";
const NETWORK = "cloudflare";
const TIMEOUT_MS = 5000;

function iso(d, minute = false) {
  const s = d.toISOString(); // 2026-11-03T14:05:00.123Z
  return minute ? s.slice(0, 16) + "Z" : s;
}

function checks(env, aws) {
  const call = (url, init, service) => aws.fetch(url, { ...init, aws: { service, region: REGION }, signal: AbortSignal.timeout(TIMEOUT_MS) });
  const mustOk = async (p) => {
    const r = await p;
    if (!r.ok) {
      const e = new Error(`HTTP ${r.status}`);
      e.status = r.status;
      e.code = r.headers.get("x-amzn-errortype") || r.headers.get("x-amz-error-code") || "";
      throw e;
    }
    return r;
  };
  return [
    ["control", "HTTPS GET", () => mustOk(fetch(env.CONTROL_URL || "https://www.google.com/generate_204", { signal: AbortSignal.timeout(TIMEOUT_MS) }))],
    ["s3", "GetObject", () => mustOk(call(`https://${env.PROBE_BUCKET}.s3.${REGION}.amazonaws.com/${env.PROBE_OBJECT_KEY || "probe.txt"}`, {}, "s3"))],
    ["dynamodb", "GetItem", () => mustOk(call(`https://dynamodb.${REGION}.amazonaws.com/`, {
      method: "POST", headers: { "Content-Type": "application/x-amz-json-1.0", "X-Amz-Target": "DynamoDB_20120810.GetItem" },
      body: JSON.stringify({ TableName: env.PROBE_TABLE, Key: JSON.parse(env.PROBE_TABLE_KEY || '{"pk":{"S":"probe"}}') }) }, "dynamodb"))],
    ["lambda", "Invoke", async () => {
      const r = await mustOk(call(`https://lambda.${REGION}.amazonaws.com/2015-03-31/functions/${env.PROBE_FUNCTION}/invocations`, { method: "POST", body: "{}" }, "lambda"));
      if (r.headers.get("X-Amz-Function-Error")) throw new Error("FunctionError:" + r.headers.get("X-Amz-Function-Error"));
    }],
    ["ec2", "DescribeInstances", () => mustOk(call(`https://ec2.${REGION}.amazonaws.com/?Action=DescribeInstances&Version=2016-11-15&MaxResults=5`, {}, "ec2"))],
    ["sts", "GetCallerIdentity", () => mustOk(call(`https://sts.${REGION}.amazonaws.com/`, {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: "Action=GetCallerIdentity&Version=2011-06-15" }, "sts"))],
  ];
}

const ascii = (s, n = 160) => String(s).replace(/[^\x20-\x7e]/g, "?").slice(0, n);

// Same failure kinds as probe/checks.py classify(): only some of them mean the service was down.
function classify(e) {
  const st = Number.isInteger(e.status) ? e.status : null;
  if (st === 429 || /Throttl|TooManyRequests|SlowDown|RequestLimitExceeded/.test(e.code || "")) return "throttled";
  if (st !== null && st >= 500) return "server_error";
  if (st !== null && st >= 400) return "client_error";
  if (e.name === "TimeoutError" || e.name === "AbortError") return "timeout";
  if (e.name === "TypeError") return "network"; // fetch() rejects with TypeError when the connection fails
  return "other";
}

async function runCheck(fn) {
  const t0 = Date.now();
  try {
    await fn();
    return { ok: true, kind: "ok", latency_ms: Date.now() - t0, error: null, status: null };
  } catch (e) {
    return { ok: false, kind: classify(e), latency_ms: Date.now() - t0, error: ascii(`${e.name}: ${e.message}`), status: Number.isInteger(e.status) ? e.status : null };
  }
}

export async function probeOnce(env, now = new Date()) {
  const aws = new AwsClient({ accessKeyId: env.AWS_ACCESS_KEY_ID, secretAccessKey: env.AWS_SECRET_ACCESS_KEY, region: REGION });
  const list = checks(env, aws);
  const results = await Promise.all(list.map(([, , fn]) => runCheck(fn)));
  const host = ascii(`cloudflare-workers ${env.CF_COLO || ""}`.trim(), 80);
  return list.map(([service, op], i) => ({ v: 1, network: NETWORK, host, target: REGION, service, op,
    minute: iso(now, true), at: iso(now), ...results[i] }));
}

// Storage: Cloudflare D1 (free, no card). Results are pulled into the public `data` branch by the GitHub probe run,
// so D1 only needs to hold the last few days.
//   runs(name TEXT PRIMARY KEY, day TEXT, body TEXT)    name = "<YYYY-MM-DD>/<HHMM>[-<seq>].jsonl"
//   heads(network TEXT PRIMARY KEY, body TEXT)
const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS runs (name TEXT PRIMARY KEY, day TEXT NOT NULL, body TEXT NOT NULL)",
  "CREATE INDEX IF NOT EXISTS runs_day ON runs (day, name)",
  "CREATE TABLE IF NOT EXISTS heads (network TEXT PRIMARY KEY, body TEXT NOT NULL)",
];
const KEEP_DAYS = 3;

async function ensureSchema(db) {
  await db.batch(SCHEMA.map((q) => db.prepare(q)));
}

async function getHead(db) {
  const row = await db.prepare("SELECT body FROM heads WHERE network = ?").bind(NETWORK).first();
  return row ? JSON.parse(row.body) : null;
}

export async function probeMinute(env, now) {
  if (!env.AWS_ACCESS_KEY_ID || !env.AWS_SECRET_ACCESS_KEY || !env.PROBE_SIGNING_KEY) return { skipped: "secrets not set yet" };
  const db = env.DB;
  await ensureSchema(db);
  const head = await getHead(db);
  if (head && head.at && head.at.slice(0, 16) === iso(now).slice(0, 16)) return { skipped: "minute already probed" };
  const key = await loadPrivate(env.PROBE_SIGNING_KEY);
  let { seq, hash } = head || { seq: 0, hash: GENESIS };
  const sealed = [];
  const rounds = Math.max(1, parseInt(env.PROBE_ROUNDS || "6", 10));
  for (let k = 0; k < rounds; k++) {
    if (k) await new Promise((r) => setTimeout(r, Math.max(0, now.getTime() + (k * 60000) / rounds - Date.now())));
    for (const rec of await probeOnce(env, k ? new Date() : now)) {
      rec.minute = iso(now, true); // every round in this minute belongs to it
      seq += 1;
      const r = await seal(rec, hash, seq, key);
      hash = r.hash;
      sealed.push(r);
    }
  }
  const day = iso(now).slice(0, 10), hhmm = iso(now).slice(11, 16).replace(":", "");
  let name = `${day}/${hhmm}.jsonl`;
  if (await db.prepare("SELECT 1 FROM runs WHERE name = ?").bind(name).first()) name = `${day}/${hhmm}-${sealed[0].seq}.jsonl`;
  // same line format as Python: sorted keys, no spaces
  const line = (r) => JSON.stringify(Object.fromEntries(Object.keys(r).sort().map((k) => [k, r[k]])));
  const cutoff = new Date(now.getTime() - KEEP_DAYS * 86400000).toISOString().slice(0, 10);
  await db.batch([
    db.prepare("INSERT INTO runs (name, day, body) VALUES (?, ?, ?)").bind(name, day, sealed.map(line).join("\n") + "\n"),
    db.prepare("INSERT INTO heads (network, body) VALUES (?, ?) ON CONFLICT(network) DO UPDATE SET body = excluded.body")
      .bind(NETWORK, JSON.stringify({ seq, hash, at: iso(now) })),
    db.prepare("DELETE FROM runs WHERE day < ?").bind(cutoff),
  ]);
  return { name, records: sealed.length, seq };
}

const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*" } });

export default {
  async scheduled(event, env, ctx) {
    await probeMinute(env, new Date(event.scheduledTime));
  },

  // Read-only feed for the GitHub run that copies results into the public data branch. Everything here is public anyway.
  //   GET /head                              -> {"seq":..,"hash":..,"at":..}
  //   GET /runs?day=YYYY-MM-DD&after=<name>  -> {"runs":[{"name":"YYYY-MM-DD/HHMM.jsonl","body":"..."}], "more": bool}
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method !== "GET") return json({ error: "read only" }, 405);
    await ensureSchema(env.DB);
    if (url.pathname === "/head") return json(await getHead(env.DB));
    if (url.pathname === "/runs") {
      const day = url.searchParams.get("day") || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return json({ error: "day=YYYY-MM-DD required" }, 400);
      const after = url.searchParams.get("after") || "";
      const limit = 60;
      const { results } = await env.DB.prepare("SELECT name, body FROM runs WHERE day = ? AND name > ? ORDER BY name LIMIT ?")
        .bind(day, after, limit + 1).all();
      return json({ runs: results.slice(0, limit), more: results.length > limit });
    }
    return json({ network: NETWORK, endpoints: ["/head", "/runs?day=YYYY-MM-DD&after=<name>"] });
  },
};
