// Tamper-evident records: the JavaScript twin of probe/chain.py. Both must produce byte-identical canonical JSON.
// Rules: keys sorted, no spaces, ASCII only, values are strings, integers, booleans or null (never floats).

export const GENESIS = "0".repeat(64);
const PKCS8_ED25519_PREFIX = "302e020100300506032b657004220420"; // wraps a raw 32-byte seed for WebCrypto import

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (h) => new Uint8Array(h.match(/../g).map((x) => parseInt(x, 16)));
const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const fromB64 = (s) => Uint8Array.from(atob(s.trim()), (c) => c.charCodeAt(0));

export function canonical(rec) {
  const keys = Object.keys(rec).filter((k) => k !== "hash" && k !== "sig").sort();
  const parts = keys.map((k) => {
    const v = rec[k];
    if (typeof v === "number" && !Number.isInteger(v)) throw new Error(`field ${k} is a float; records hold integers only`);
    if (typeof v === "string" && !/^[\x00-\x7f]*$/.test(v)) throw new Error(`field ${k} is not ASCII`);
    if (v !== null && typeof v === "object") throw new Error(`field ${k} is nested; records are flat`);
    return JSON.stringify(k) + ":" + JSON.stringify(v === undefined ? null : v);
  });
  return new TextEncoder().encode("{" + parts.join(",") + "}");
}

export async function loadPrivate(seedB64) {
  const seed = fromB64(seedB64);
  if (seed.length !== 32) throw new Error("the signing key must be a base64-encoded 32-byte Ed25519 seed");
  const pkcs8 = new Uint8Array([...fromHex(PKCS8_ED25519_PREFIX), ...seed]);
  return crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, false, ["sign"]);
}

export async function seal(rec, prevHash, seq, key) {
  const out = { ...rec, prev: prevHash, seq };
  const digest = hex(await crypto.subtle.digest("SHA-256", canonical(out)));
  out.hash = digest;
  out.sig = b64(await crypto.subtle.sign({ name: "Ed25519" }, key, fromHex(digest)));
  return out;
}
