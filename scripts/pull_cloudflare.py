"""Copy the Cloudflare probe's results from its Worker feed into the checked-out data branch.

  python scripts/pull_cloudflare.py --url https://outage-probe.<account>.workers.dev --store store

Fetches yesterday's and today's per-minute files newer than the last one already in the store, plus the chain head.
Nothing is trusted here: the status build and the daily file verify every signature and hash afterwards.
"""
import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

NET = "cloudflare"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "outage-telemetry-sync"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--store", default="store")
    a = ap.parse_args()
    base, store = a.url.rstrip("/"), Path(a.store)
    now = datetime.now(timezone.utc)
    added = 0
    for day in [(now - timedelta(days=1)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")]:
        folder = store / "runs" / NET / day
        have = sorted(p.name for p in folder.glob("*.jsonl")) if folder.exists() else []
        after = f"{day}/{have[-1]}" if have else ""
        while True:
            d = get(f"{base}/runs?" + urllib.parse.urlencode({"day": day, "after": after}))
            for r in d["runs"]:
                day_part, file = r["name"].split("/")
                if day_part != day or "/" in file or not file.endswith(".jsonl"):
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                (folder / file).write_text(r["body"])
                after = r["name"]
                added += 1
            if not d.get("more"):
                break
    head = get(f"{base}/head")
    if head:
        p = store / "chains" / NET / "head.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(head))
    print(f"cloudflare: {added} new minute files")


if __name__ == "__main__":
    main()
