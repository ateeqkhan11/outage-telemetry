// Full-page screenshots of the example-data app for outreach emails, using the installed Chrome over DevTools.
//   node shoot.mjs <base-url> <session-cookie> <out-dir> <width> <scheme> path:name [path:name ...]
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [base, sid, outDir, width, scheme, ...shots] = process.argv.slice(2);
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new", "--remote-debugging-port=9333", `--user-data-dir=${mkdtempSync(join(tmpdir(), "shoot-"))}`,
   "--hide-scrollbars", "--force-device-scale-factor=2", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 50 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch("http://127.0.0.1:9333/json")).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const waiting = new Map(); const events = [];
ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); } else events.push(d); });
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Page.enable"); await send("Network.enable");
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: scheme }] });
await send("Network.setCookie", { name: "nimbus_session", value: sid, url: base, httpOnly: true });
for (const s of shots) {
  const [path, name] = s.split(":");
  await send("Emulation.setDeviceMetricsOverride", { width: +width, height: +width < 600 ? 844 : 900, deviceScaleFactor: 2, mobile: +width < 600 });
  await send("Page.navigate", { url: base + path });
  await sleep(2500);
  const { result } = await send("Runtime.evaluate", { expression: "document.documentElement.scrollHeight", returnByValue: true });
  const h = process.env.FIRST_SCREEN ? (+width < 600 ? 844 : 900) : result.result.value;
  await send("Emulation.setDeviceMetricsOverride", { width: +width, height: h, deviceScaleFactor: 2, mobile: +width < 600 });
  await sleep(600);
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: !process.env.FIRST_SCREEN });
  writeFileSync(join(outDir, `${name}.png`), Buffer.from(shot.result.data, "base64"));
  console.log(`${name}.png ${width}x${h}`);
}
ws.close(); chrome.kill();
