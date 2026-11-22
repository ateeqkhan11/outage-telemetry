"""The public website (site/): copy guard, Methodology drift, buttons, no scripts, links that resolve."""
import json
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "scripts"))

import build_methodology  # noqa: E402
import copy_guard  # noqa: E402

APP = "https://app.nimbusindex.com"
APPROVED = build_methodology.APPROVED_LINE
PAGES = sorted(SITE.rglob("*.html"))
assert PAGES, "no pages under site/"
METHODOLOGY = SITE / "methodology" / "index.html"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.ids, self.stylesheets = [], set(), []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and "href" in a:
            self.links.append((a["href"], a.get("class", "")))
        if tag == "link" and a.get("rel") == "stylesheet":
            self.stylesheets.append(a["href"])


def parse(path: Path) -> Links:
    p = Links()
    p.feed(path.read_text())
    return p


def text(path: Path) -> str:
    return copy_guard.visible_text(path)


# ---------- copy guard ----------

def test_copy_guard_passes_on_the_site():
    checked, failures = copy_guard.check_dirs([SITE])
    assert checked >= 2
    assert failures == []


def test_copy_guard_passes_on_public_and_email_templates_when_present():
    dirs = [d for d in (ROOT / "templates" / "public", ROOT / "templates" / "email") if d.exists()]
    if not dirs:
        pytest.skip("no templates/public or templates/email on this branch")
    assert copy_guard.check_dirs(dirs)[1] == []


def _copy_site(tmp_path: Path) -> Path:
    dst = tmp_path / "site"
    shutil.copytree(SITE, dst)
    return dst


def test_banned_phrase_on_landing_fails_naming_file_and_phrase(tmp_path, capsys):
    site = _copy_site(tmp_path)
    page = site / "index.html"
    page.write_text(page.read_text().replace("</h1>", "</h1><p>Verified monitoring of AWS.</p>", 1))
    assert copy_guard.main([str(site)]) == 1
    err = capsys.readouterr().err
    assert str(page) in err and '"Verified"' in err and '"monitoring"' in err


@pytest.mark.parametrize("phrase", [
    "two independent companies", "tamper-evident records", "live monitoring", "99.95% uptime",
    "SOC 2", "trigger-ready", "Trusted by leading MGAs", "$499 per month", "multi-network",
    "alerts within 2 minutes", "backtested",
])
def test_each_banned_category_is_caught_on_marketing_pages(tmp_path, phrase):
    site = _copy_site(tmp_path)
    page = site / "index.html"
    page.write_text(page.read_text().replace("</h1>", f"</h1><p>{phrase}</p>", 1))
    checked, failures = copy_guard.check_dirs([site])
    assert failures and all(f.startswith(f"{page}: ") for f in failures), phrase


def _plant(page: Path, html: str) -> None:
    page.write_text(page.read_text(encoding="utf-8").replace("</h1>", f"</h1>{html}", 1), encoding="utf-8")


def test_methodology_method_words_are_allowed(tmp_path):
    site = _copy_site(tmp_path)
    page = site / "methodology" / "index.html"
    _plant(page, "<p>Two independent companies must each see it. At least 3 independent companies.</p>")
    assert copy_guard.check_dirs([site])[1] == []
    assert copy_guard.main([str(site / "methodology")]) == 0          # the exception holds when only that folder is checked
    assert copy_guard.main([str(page)]) == 0


def test_allow_list_only_covers_the_methodology_page(tmp_path):
    site = _copy_site(tmp_path)
    for rel in ("index.html", "methodology-notes/index.html", "methodology/other.html", "methodologyx.html"):
        p = site / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<p>Two independent companies must each see it.</p>", encoding="utf-8")
        assert copy_guard.check_dirs([p])[1], rel


def test_methodology_is_still_checked_for_other_banned_phrases(tmp_path):
    site = _copy_site(tmp_path)
    page = site / "methodology" / "index.html"
    page.write_text(page.read_text().replace("</h1>", "</h1><p>Live monitoring, SOC 2 certified.</p>", 1))
    failures = copy_guard.check_dirs([site])[1]
    assert failures and all(f.startswith(f"{page}: ") for f in failures)


def test_methodology_without_the_allow_list_would_fail(tmp_path):
    site = _copy_site(tmp_path)
    page = site / "methodology" / "index.html"
    _plant(page, "<p>Two independent companies must each see it.</p>")
    empty = tmp_path / "allow.txt"
    empty.write_text("# nothing allowed\n")
    assert copy_guard.check_dirs([site])[1] == []                       # passes with the real allow-list ...
    failures = copy_guard.check_dirs([site], allow_file=empty)[1]       # ... and fails without it
    assert failures and all(f.startswith(f"{page}: ") for f in failures)
    assert any('"Two independent companies"' in f or '"independent companies"' in f for f in failures)


@pytest.mark.parametrize("html", [
    "<p>real\u2011time</p>", "<p>moni&shy;toring</p>", "<p>tamper\u2010evident</p>", "<p>live\u200b monitoring</p>",
    "<p>tamper&#8212;evident</p>", "<p>\uff33\uff2f\uff23 2</p>",
])
def test_unicode_tricks_do_not_hide_banned_phrases(tmp_path, html):
    site = _copy_site(tmp_path)
    _plant(site / "index.html", html)
    assert copy_guard.check_dirs([site])[1], html


@pytest.mark.parametrize("html", [
    '<td data-label="Live monitoring">x</td>', '<input value="Live monitoring">',
    '<span aria-description="Live monitoring">x</span>',
])
def test_text_in_attributes_is_checked(tmp_path, html):
    site = _copy_site(tmp_path)
    _plant(site / "index.html", html)
    assert copy_guard.check_dirs([site])[1], html


def test_svg_text_is_checked(tmp_path):
    site = _copy_site(tmp_path)
    (site / "assets" / "badge.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>SOC 2</text></svg>')
    failures = copy_guard.check_dirs([site])[1]
    assert failures and failures[0].startswith(str(site / "assets" / "badge.svg"))


def test_empty_or_missing_banned_list_cannot_pass(tmp_path, capsys):
    empty = tmp_path / "banned.txt"
    empty.write_text("# comments only\n\n")
    assert copy_guard.main([str(SITE), "--banned", str(empty)]) == 2
    assert "no banned patterns loaded" in capsys.readouterr().err
    assert copy_guard.main([str(SITE), "--banned", str(tmp_path / "nope.txt")]) == 2
    assert "missing list" in capsys.readouterr().err


def test_guard_cli_reports_missing_folder(tmp_path):
    assert copy_guard.main([str(tmp_path / "nope")]) == 2


def test_publish_script_runs_the_guard_before_copying():
    sh = (ROOT / "infra" / "aws" / "publish_site.sh").read_text()
    guard, copy = sh.index("copy_guard.py"), sh.index("cp -r")
    assert guard < copy and "build_methodology.py\" --check" in sh[:copy]
    assert '"$rc" -eq 1' in sh and "could not run" in sh


# ---------- Methodology is generated ----------

def test_methodology_page_matches_the_generator():
    committed = (SITE / "methodology" / "index.html").read_text()
    assert committed == build_methodology.build(), "regenerate: python3 scripts/build_methodology.py"


def test_rules_change_changes_the_page(tmp_path):
    for sub in ("copy", "keys"):
        shutil.copytree(ROOT / sub, tmp_path / sub)
    rules = json.loads((ROOT / "trigger_v1_rolling.json").read_text())
    rules["operators_required"] = 3
    (tmp_path / "trigger_v1_rolling.json").write_text(json.dumps(rules))
    changed = build_methodology.build(tmp_path)
    assert changed != build_methodology.build()
    assert "Three companies must see it" in changed and "at least 3 companies" in changed
    assert "Two companies must see it" not in changed and "at least 2 companies" not in changed
    assert "needs 3 companies" in changed


def test_missing_key_file_says_not_yet_published(tmp_path):
    for sub in ("copy", "keys"):
        shutil.copytree(ROOT / sub, tmp_path / sub)
    shutil.copy(ROOT / "trigger_v1_rolling.json", tmp_path)
    (tmp_path / "keys" / "cloudflare.pub").unlink()
    html = build_methodology.build(tmp_path)
    row = re.search(r"<tr><td class=\"term\">Cloudflare Workers</td><td data-label=\"Public key\">(.*?)</td></tr>", html)
    assert row and "Key not yet published for this network." in row.group(1)
    assert (ROOT / "keys" / "github.pub").read_text().strip() in html


def _tmp_root(tmp_path: Path, **rule_changes) -> Path:
    for sub in ("copy", "keys"):
        shutil.copytree(ROOT / sub, tmp_path / sub)
    rules = json.loads((ROOT / "trigger_v1_rolling.json").read_text())
    rules.update(rule_changes)
    (tmp_path / "trigger_v1_rolling.json").write_text(json.dumps(rules))
    return tmp_path


def test_no_reference_network_omits_its_section(tmp_path):
    html = build_methodology.build(_tmp_root(tmp_path, reference_networks=[]))
    assert 'id="rule-reference-network"' not in html and "#rule-reference-network" not in html
    assert "The reference network fails" not in html


@pytest.mark.parametrize("change, message", [
    ({"default_definition": "nope"}, "default_definition"),
    ({"operators": {"github": "microsoft"}}, "no operator"),
])
def test_bad_rules_raise_clearly(tmp_path, change, message):
    with pytest.raises(build_methodology.InputError, match=message):
        build_methodology.build(_tmp_root(tmp_path, **change))


def test_bad_changelog_and_key_raise_clearly(tmp_path):
    root = _tmp_root(tmp_path)
    log = root / "copy" / "methodology-changelog.md"
    log.write_text(log.read_text() + "\nstray text\n")
    with pytest.raises(build_methodology.InputError, match="line"):
        build_methodology.build(root)
    shutil.copy(ROOT / "copy" / "methodology-changelog.md", log)
    (root / "keys" / "github.pub").write_text("not-a-key\n")
    with pytest.raises(build_methodology.InputError, match="Ed25519"):
        build_methodology.build(root)


def test_methodology_tables():
    html = METHODOLOGY.read_text(encoding="utf-8")
    assert re.search(r'<td class="term">AWS Lambda, Oregon \(us-west-2\)</td><td data-label="Company">AWS</td>'
                     r'<td data-label="Counted">Shown, never counted \(reference\)</td>', html)
    assert "<dt>Counted companies</dt><dd>Cloudflare and Microsoft</dd>" in html
    assert "Azure" not in html


def test_methodology_content():
    page = SITE / "methodology" / "index.html"
    t, ids = text(page), parse(page).ids
    rules = json.loads((ROOT / "trigger_v1_rolling.json").read_text())
    assert APPROVED in t and "Pending independent review" in t
    assert t.count(rules["version"]) >= 6                    # head + every rule section
    for anchor in ("rule-what-counts-as-down", "rule-two-companies", "rule-start-and-end", "rule-reference-network",
                   "rule-coverage", "when-it-does-not-fire", "why-clocks-differ", "scope", "public-keys", "change-log"):
        assert anchor in ids
    for words in ("Hard down", "Degraded", "90% or more", "10% or more", "95% or more of the last 24 h",
                  "within the last 15 minutes", "not enough data", "never treated as up", "never counted",
                  "One company's network fails", "The reference network fails", "A status page reports an incident",
                  "Crowd reports spike", "The Certificate key will be published here", "Timing and counting",
                  "no minimum number of calls", "All times are UTC", "Throttling is the one client error that counts",
                  "Pending independent review (no reviewer appointed yet)",
                  "us-east-1", "S3, DynamoDB, Lambda, EC2 and STS"):
        assert words in t, words
    for net, runs_on, since in build_methodology.NETWORKS:
        assert runs_on in t and since in t
        assert (ROOT / "keys" / f"{net}.pub").read_text().strip() in t


# ---------- Landing page ----------

def test_methodology_keeps_request_access_on_phones():
    html = METHODOLOGY.read_text(encoding="utf-8")
    assert f'<p class="phone-cta"><a class="btn btn-primary" href="{APP}/request-access">' in html
    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    phone = css[css.index("@media (max-width: 720px)"):]
    assert ".phone-cta { display: block; }" in phone[:phone.index("@media (max-width: 480px)")]


def test_landing_content_and_buttons():
    page = SITE / "index.html"
    t, links = text(page), parse(page).links
    assert APPROVED in t
    for words in ("In development · pilot places open", "A reference clock for cloud outages", "Key terms of the pilot",
                  "What it is", "Scope today", "Method", "Pilot", "MGAs", "Insurers", "Reinsurers",
                  "© 2026 Nimbus Index", "Nothing on this site is an offer of insurance. Nimbus Index provides data only."):
        assert words in t, words
    hrefs = [h for h, _ in links]
    assert f"{APP}/request-access" in hrefs and f"{APP}/sign-in" in hrefs and "/methodology/" in hrefs
    band = page.read_text().split('<section class="band"', 1)[1].split("</section>", 1)[0]
    assert f'href="{APP}/request-access">Request early access</a>' in band
    assert f'href="{APP}/sign-in">Sign in</a>' in band


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_no_scripts_no_inline_styles_one_stylesheet(page):
    html = page.read_text()
    assert "<script" not in html.lower()
    assert " style=" not in html and "<style" not in html.lower()
    assert "/assets/site.css" in parse(page).stylesheets


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(SITE)))
def test_every_internal_link_resolves(page):
    p = parse(page)
    refs = [h for h, _ in p.links] + p.stylesheets
    for href in refs:
        u = urlparse(href)
        if u.scheme in ("http", "https", "mailto"):
            continue
        if not u.path:                                   # same-page anchor
            assert u.fragment in p.ids, href
            continue
        target = SITE / u.path.lstrip("/") if u.path.startswith("/") else page.parent / u.path
        if target.is_dir() or u.path.endswith("/"):
            target = target / "index.html"
        assert target.is_file(), f"{page.relative_to(SITE)}: {href}"
        if u.fragment:
            assert u.fragment in parse(target).ids, href


def test_only_app_links_leave_the_site():
    for page in PAGES:
        for href, _ in parse(page).links:
            if href.startswith("http"):
                assert href in (f"{APP}/request-access", f"{APP}/sign-in"), href
