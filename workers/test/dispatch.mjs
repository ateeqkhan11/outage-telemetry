// node workers/test/dispatch.mjs — checks the GitHub dispatch from the Worker's timer (fix 3).
import assert from "node:assert/strict";
import { dispatchGithub } from "../src/index.js";

const env = { GITHUB_DISPATCH_TOKEN: "test-token", DISPATCH_REPO: "o/r" };
const calls = [];
const fake = (status) => async (url, init) => { calls.push({ url, init }); return { ok: status < 300, status }; };

assert.equal(await dispatchGithub(env, new Date("2026-11-22T10:04:00Z"), fake(204)), "not a dispatch minute");
assert.equal(calls.length, 0);
assert.equal(await dispatchGithub({}, new Date("2026-11-22T10:03:00Z"), fake(204)), "dispatch not configured");
assert.equal(await dispatchGithub(env, new Date("2026-11-22T10:03:00Z"), fake(204)), "dispatched");
assert.equal(calls[0].url, "https://api.github.com/repos/o/r/actions/workflows/probe.yml/dispatches");
assert.deepEqual(JSON.parse(calls[0].init.body), { ref: "main", inputs: { started_by: "cloudflare-cron" } });
assert.equal(await dispatchGithub(env, new Date("2026-11-22T10:58:00Z"), fake(401)), "dispatch failed: HTTP 401");
assert.equal(await dispatchGithub(env, new Date("2026-11-22T10:08:00Z"), async () => { throw new TypeError("x"); }), "dispatch failed: TypeError");
console.log("dispatch ok");
