# Record format (v1)

One JSON object per line. One record = one check, one minute, one probe network.

```json
{"at":"2026-11-02T00:20:32.021Z","error":null,"hash":"b9af…db04","host":"github-actions run 123 Linux",
 "kind":"ok","latency_ms":164,"minute":"2026-11-02T00:20Z","network":"github","ok":true,"op":"GetObject",
 "prev":"0000…0000","seq":1,"service":"s3","sig":"qeKK…CBA==","status":null,"target":"us-east-1","v":1}
```

| Field | Meaning |
|---|---|
| `v` | Record format version (1) |
| `network` | Probe network: `github`, `azure`, `cloudflare`, `gcp`, `vps` |
| `host` | Which machine or run did the probing |
| `target` | AWS region probed (`us-east-1`) |
| `service`, `op` | What was called: `control` (outside AWS), `s3`, `dynamodb`, `lambda`, `ec2`, `sts` |
| `minute` | UTC minute the check belongs to (`YYYY-MM-DDTHH:MMZ`) |
| `at` | UTC time the round of checks started, in milliseconds |
| `ok` | Whether the call succeeded |
| `kind` | `ok`, `server_error`, `timeout`, `network`, `throttled`, `client_error` or `other` |
| `latency_ms` | Time taken, in whole milliseconds |
| `status` | HTTP status if AWS answered, else null |
| `error` | Error code and message, ASCII only, at most 160 characters |
| `seq` | Position on this network's chain, starting at 1 |
| `prev` | `hash` of the previous record on this network (64 zeros for the first) |
| `hash` | SHA-256 (hex) of the canonical JSON of every field except `hash` and `sig` |
| `sig` | Ed25519 signature (base64) of the 32 hash bytes, using this network's key |

## Canonical JSON

This is what gets hashed:
- every field except `hash` and `sig`;
- keys sorted, separators `,` and `:` with no spaces;
- ASCII only;
- values that are strings, integers, booleans or null. No floats, because Python and JavaScript print them
  differently.

## Verifying

1. Recompute the hash and check it matches.
2. Check the signature against `keys/<network>.pub`, a base64 raw 32-byte Ed25519 public key.
3. Check that `prev` equals the previous record's `hash`, and that `seq` goes up by one each time.

`python -m probe.verify` does all of this.
