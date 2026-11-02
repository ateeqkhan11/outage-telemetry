// Cloudflare Worker probe: every minute (cron), run the control check and the 5 AWS us-east-1 checks, seal the
// results onto the "cloudflare" chain and save them to the same R2 bucket as the other networks.
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

export default {
  async scheduled(event, env, ctx) {
    const now = new Date(event.scheduledTime);
    const key = await loadPrivate(env.PROBE_SIGNING_KEY);
    const headObj = await env.TELEMETRY.get(`chains/${NETWORK}/head.json`);
    let { seq, hash } = headObj ? await headObj.json() : { seq: 0, hash: GENESIS };
    const sealed = [];
    for (const rec of await probeOnce(env, now)) {
      seq += 1;
      const r = await seal(rec, hash, seq, key);
      hash = r.hash;
      sealed.push(r);
    }
    const day = iso(now).slice(0, 10), hhmm = iso(now).slice(11, 16).replace(":", "");
    let name = `runs/${NETWORK}/${day}/${hhmm}.jsonl`;
    if (await env.TELEMETRY.head(name)) name = `runs/${NETWORK}/${day}/${hhmm}-${sealed[0].seq}.jsonl`;
    // same line format as Python: sorted keys, no spaces
    const line = (r) => JSON.stringify(Object.fromEntries(Object.keys(r).sort().map((k) => [k, r[k]])));
    await env.TELEMETRY.put(name, sealed.map(line).join("\n") + "\n");
    await env.TELEMETRY.put(`chains/${NETWORK}/head.json`, JSON.stringify({ seq, hash, at: iso(now) }));
  },
};
