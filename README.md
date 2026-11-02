# outage-telemetry

Independent, tamper-evident measurements of whether AWS us-east-1 is up.

Probes on separate networks call five core AWS services every minute. Every result is signed, and each result is
chained to the one before it, so anyone can check that nothing was changed or removed afterwards. An outage counts only
when probes run by **two different operators** see the same service failing while their own connection is working.

- **Who it's for:** parametric insurers, MGAs and reinsurers who need the data that decides a payout to come from an
  independent source.
- **Status:** Sprint 1 (2–8 November 2026). Trigger rules are a draft until 13 November.

## What gets measured

Every minute, from each probe network:

| Check | Call | Set-up needed |
|---|---|---|
| control | HTTPS GET to a site outside AWS | none |
| s3 | `GetObject` on one tiny file | a bucket with `probe.txt` |
| dynamodb | `GetItem` on one item | an on-demand table |
| lambda | `Invoke` a do-nothing function | one function |
| ec2 | `DescribeInstances` | none (works on an empty account) |
| sts | `GetCallerIdentity` | none |

The **control** check is what keeps a probe's own problems out of the data. If a probe can't reach the outside world,
that minute is marked "probe down" for that network instead of counting as an AWS failure.

Each failure also gets a **kind**:
- `server_error`: HTTP 5xx
- `timeout`
- `network`: no connection
- `throttled`
- `client_error`: HTTP 4xx, such as bad credentials
- `other`

Only the kinds listed in `trigger_v1.json` count toward an outage. A `client_error` proves AWS answered, so it never
counts as AWS being down.

## Probe networks and independence

| Network | Runs on | Operator | Schedule |
|---|---|---|---|
| `github` | GitHub Actions | Microsoft (Azure) | Every 5 minutes, probing once a minute for 6 minutes |
| `azure` | Azure Functions | Microsoft | Every minute |
| `cloudflare` | Cloudflare Workers | Cloudflare | Every minute |
| `gcp` or `vps` (planned) | Google Cloud Run, or a small non-Microsoft VPS | Google, or independent | Every minute |

GitHub's hosted runners are Azure machines, so `github` and `azure` count as **one operator**. The 2-of-3 rule needs
Cloudflare plus one non-Microsoft network to be truly independent.

## How the records are protected

Each record (one check, one minute, one network) is a line of JSON with:
- `seq`: its position on that network's chain;
- `prev`: the hash of the record before it;
- `hash`: the SHA-256 of its canonical JSON;
- `sig`: an Ed25519 signature over that hash, made with the network's private key.

The canonical JSON has sorted keys, no spaces, ASCII text only and integers only, and is identical in Python and
JavaScript (tested). See [docs/RECORD_FORMAT.md](docs/RECORD_FORMAT.md).

- **Public keys** are in `keys/<network>.pub`. Private keys live only in each platform's secrets.
- **Per-minute storage:** results go to Cloudflare R2, one object per minute (R2 can't append).
- **Daily file:** once a day, a workflow builds a verified file per network, plus a manifest of SHA-256 hashes, and
  commits them to the **`data` branch**. That commit is the public timestamp: a later change to any record would no
  longer match it.
- **Check it yourself:** `python -m probe.verify daily/<date>/`.

## Repository layout

```
probe/                 Python probe (GitHub Actions, Azure, local)
  checks.py            the six checks and failure classification (swap in SRE's script here)
  chain.py             hash chain and Ed25519 signatures
  run.py               probe every minute, seal, save
  store.py             Cloudflare R2 or a local folder
  daily.py             build and verify each day's files and manifest
  detect.py            outage events from all networks, using trigger_v1.json
  verify.py            check any results file with the public keys
workers/               Cloudflare Workers probe (JavaScript, same record format)
azure/                 Azure Functions timer (uses the Python probe)
infra/aws/             AWS account setup and the least-privilege policy
.github/workflows/     probe-github (scheduled probe) and daily-file
trigger_v1.json        draft outage rules for the advisors
keys/                  public keys (commit) - never private ones
```

## Sprint 1 checklist (2–8 November)

1. **Repo and AWS account.**
   - Create the public GitHub repo, push this, and protect `main`. Only `daily-file` pushes, to `data`.
   - Set up the AWS account: [infra/aws/SETUP.md](infra/aws/SETUP.md) covers root MFA, the $5 budget alarm and the
     probe-only user.
2. **The five test resources.** Also in [infra/aws/SETUP.md](infra/aws/SETUP.md).
3. **Run locally.** Use SRE's script in `probe/checks.py` if it differs from what's here.
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
   .venv/bin/python scripts/genkey.py --network local        # prints the private key once
   export PROBE_SIGNING_KEY=...  AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...
   export PROBE_BUCKET=...  PROBE_TABLE=outage-probe  PROBE_FUNCTION=outage-probe-hello
   .venv/bin/python -m probe.run --network local --minutes 30 --local out
   .venv/bin/python -m probe.daily --date $(date -u +%F) --keys keys --local out
   ```
   Expect every check `ok`, and timings of a few hundred milliseconds at most.
4. **GitHub Actions to R2.**
   - Create a Cloudflare account and an R2 bucket named `outage-telemetry`, then an R2 API token.
   - Run `scripts/genkey.py --network github` and commit `keys/github.pub`.
   - Add the repository **secrets**: `PROBE_AWS_ACCESS_KEY_ID`, `PROBE_AWS_SECRET_ACCESS_KEY`,
     `PROBE_SIGNING_KEY_GITHUB`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
   - Add the repository **variables**: `R2_BUCKET`, `PROBE_BUCKET`, `PROBE_TABLE`, `PROBE_FUNCTION`.
   - Enable the workflows. The next day, run `daily-file` and check the longest gap in the manifest.
5. **If there's time: Azure.** Run `scripts/genkey.py --network azure`, then deploy `azure/` with the `probe` package
   copied in.
6. **Next week: Cloudflare.**
   ```bash
   cd workers && npm install && npx wrangler secret put PROBE_SIGNING_KEY && npx wrangler deploy
   ```
   Also put the two AWS keys as Worker secrets, and run `scripts/genkey.py --network cloudflare`.

**Done by Sunday** means: the repo is live, there are at least 24 hours of signed GitHub results in R2, and the first
`data` commit exists.

## Tests

```bash
.venv/bin/python -m pytest -q        # 13 tests, no network; the cross-language test needs node
```

## Known limits (v1)

- **GitHub is the gappiest network.** Its schedule is often late, so its manifest will show gaps. That's expected and
  why it doesn't count as independent of Azure.
- **Regional services only.** A single availability zone going down is planned for Q1.
- **Each network sees one path to AWS.** It measures what a customer on that network would experience.
- **Monitor the monitor.** If our own pipeline stops, the daily manifest shows it as gaps, never as AWS being down.
