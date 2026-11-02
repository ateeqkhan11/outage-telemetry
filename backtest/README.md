# Backtest: past AWS us-east-1 outages against trigger v1

- `aws_us_east_1_events.json`: the 16 outages since 2011, with UTC windows per service and their sources. 12 come from
  AWS post-event summaries; 4 come from press and status pages only, and are flagged.
- `backtest.py`: simulates three independent probe operators during each outage and runs their records through
  `probe/detect.py`, under both draft rules and three threshold settings. It also runs the must-not-pay tests.
  Writes `results.json`.
- `make_pack.py`: builds `pack.html`, the shareable pack, from `results.json`.

```bash
.venv/bin/python -m backtest.backtest && .venv/bin/python -m backtest.make_pack
```

Main findings (8 November 2026 draft):
- **The draft rule misses partial outages.** One check a minute, with every check failing, rarely adds up to a 1-hour
  wait when some calls still work.
- **The recommended rule catches them.** With 6 checks a minute and a rolling 10-minute window (10% of checks
  failing), all 8 outages our checks could see that lasted over 2 hours pay. Nothing in the must-not-pay tests does.
- **7 of 16 outages are invisible to the five checks.** Four stayed in one availability zone; three hit ELB, SimpleDB
  or Kinesis/CloudWatch. This is the basis risk to raise with buyers, and the Q1 checks list.
- **The threshold is a pricing dial.** At a 2-hour wait, 8 events pay at 10%, 3 at 25% (under both error-rate
  assumptions), and 3 at 50%.

Per-call failure rates are assumptions, because AWS only publishes service-level descriptions. The method section of
`pack.html` lists them all.
