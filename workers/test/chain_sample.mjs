// Seals a few sample records with a fixed key and prints them as JSON lines, so the Python tests can verify that
// JavaScript and Python agree byte for byte. Usage: node test/chain_sample.mjs <seed_b64>
import { GENESIS, loadPrivate, seal } from "../src/chain.js";
const key = await loadPrivate(process.argv[2]);
let prev = GENESIS;
const base = { v: 1, network: "cloudflare", host: "test", target: "us-east-1", op: "GetObject", minute: "2026-11-03T14:05Z", at: "2026-11-03T14:05:00.123Z", error: null, status: null };
const rows = [{ ...base, service: "control", ok: true, latency_ms: 31 }, { ...base, service: "s3", ok: false, latency_ms: 5002, error: "TimeoutError: The operation timed out", status: 503 }];
let seq = 0;
for (const r of rows) {
  const s = await seal(r, prev, ++seq, key);
  prev = s.hash;
  console.log(JSON.stringify(Object.fromEntries(Object.keys(s).sort().map((k) => [k, s[k]]))));
}
