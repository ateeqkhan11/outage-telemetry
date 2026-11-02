import json
from pathlib import Path

from probe.detect import detect, minute_states

CFG = json.loads((Path(__file__).parent.parent / "trigger_v1.json").read_text())


def recs(network, minute, control=True, **svc):
    out = [{"network": network, "minute": minute, "service": "control", "ok": control}]
    for s in CFG["services"]:
        out.append({"network": network, "minute": minute, "service": s, "ok": svc.get(s, True)})
    return out


def m(i):
    return f"2026-11-03T14:{i:02d}Z"


def test_two_operators_failing_is_down():
    rs = recs("github", m(0), s3=False) + recs("cloudflare", m(0), s3=False) + recs("gcp", m(0))
    assert minute_states(rs, CFG)[m(0)]["s3"] == "down"


def test_github_and_azure_count_as_one_operator():
    # both Microsoft networks fail, Cloudflare is fine: not an AWS outage
    rs = recs("github", m(0), s3=False) + recs("azure", m(0), s3=False) + recs("cloudflare", m(0))
    assert minute_states(rs, CFG)[m(0)]["s3"] == "up"


def test_probe_with_broken_internet_is_not_counted():
    # github's own connection is down (control fails, so everything fails); only cloudflare is usable
    rs = recs("github", m(0), control=False, s3=False, dynamodb=False) + recs("cloudflare", m(0), s3=False)
    assert minute_states(rs, CFG)[m(0)]["s3"] == "unknown"


def test_outage_duration_and_waiting_periods():
    rs = []
    for i in range(0, 59):
        bad = 5 <= i < 5 + 50 and i != 30          # a 50-minute outage with one "up" blip that must not split it
        rs += recs("cloudflare", m(i), lambda_=True, **({"lambda": False} if bad else {}))
        rs += recs("gcp", m(i), **({"lambda": False} if bad else {}))
    out = detect(rs, CFG)
    ev = out["by_service"]["lambda"]
    assert len(ev) == 1 and ev[0]["start"] == m(5) and ev[0]["end"] == m(54) and ev[0]["duration_min"] == 50
    assert ev[0]["meets_waiting_period"] == {"60": False, "120": False}
    assert out["region"][0]["services"] == ["lambda"]


def test_auth_errors_prove_the_service_was_up():
    rs = recs("github", m(0)) + recs("cloudflare", m(0)) + recs("gcp", m(0))
    for r in rs:
        if r["network"] in ("github", "cloudflare") and r["service"] == "s3":
            r.update(ok=False, kind="client_error")          # e.g. our credentials expired on two networks
    assert minute_states(rs, CFG)[m(0)]["s3"] == "unknown"   # only gcp is usable: not enough to call it either way


def test_rolling_rule_catches_a_partial_outage_the_minute_rule_misses():
    import random
    rolling = json.loads((Path(__file__).parent.parent / "trigger_v1_rolling.json").read_text())
    rng = random.Random(1)
    rs = []
    for i in range(150):
        t = f"2026-11-03T{12 + i // 60:02d}:{i % 60:02d}Z"
        bad = 10 <= i < 140                                   # 130 minutes where half of all calls fail
        for net in ("cloudflare", "gcp"):
            for k in range(6):                                # 6 checks a minute, as the probes run
                for r in recs(net, t, **({"lambda": rng.random() >= 0.5} if bad else {})):
                    rs.append(dict(r, at=f"{t}{k}"))
    longest = lambda cfg: max([e["duration_min"] for e in detect(rs, cfg)["region"]], default=0)
    assert longest(CFG) < 60                                  # flickers: never reaches a 1-hour wait
    assert longest(rolling) >= 120                            # seen as one outage
