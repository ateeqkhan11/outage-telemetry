"""Export the example-data app as a static, clickable preview (for sharing the mockup without a server).

  PYTHONPATH=..:. ../.venv/bin/python demo_tools/export_static.py --out <dir>      (run from app/)

Renders the signed-in pages with the app's own templates and the example data in instance/demo, then rewrites
links to sibling .html files. Forms, downloads and per-day links are switched off; a note says they work in the live
app. The first page (index.html) is written without <html>/<head>/<body> so it can be published as an Artifact page.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP = Path(__file__).resolve().parents[1]
DEMO = APP / "instance" / "demo"

STATIC_JS = """// Static preview: forms and downloads only work in the live app.
document.addEventListener("submit", function (e) { e.preventDefault(); note(); }, true);
document.addEventListener("click", function (e) { var a = e.target.closest("a[data-off]"); if (a) { e.preventDefault(); note(); } }, true);
function note() {
  var n = document.getElementById("static-note");
  if (!n) { n = document.createElement("div"); n.id = "static-note"; n.setAttribute("role", "status");
    n.textContent = "This is a static preview. Running reports, downloads and API keys work in the live app.";
    document.body.appendChild(n); }
  n.hidden = false; clearTimeout(note.t); note.t = setTimeout(function () { n.hidden = true; }, 3200);
}
"""
STATIC_CSS = """
#static-note { position: fixed; left: 50%; bottom: calc(18px + env(safe-area-inset-bottom, 0px)); transform: translateX(-50%); z-index: 50;
  background: var(--navy-deep); color: #FFF; border: 1px solid var(--navy-line); border-radius: 4px; padding: 10px 16px; font-size: 14px;
  max-width: calc(100% - 32px); box-shadow: 0 6px 20px rgba(0,0,0,.25); }
"""


def build(out: Path) -> list:
    os.environ.update(NIMBUS_SECURE_COOKIES="0", NIMBUS_DEMO="1", NIMBUS_DB=str(DEMO / "nimbus.db"),
                      NIMBUS_DATA=str(DEMO / "data"), NIMBUS_KEYS=str(DEMO / "keys"))
    from nimbus_app import create_app
    app = create_app()
    c = app.test_client()
    c.set_cookie("nimbus_session", (DEMO / ".shot_session").read_text().strip())
    anon = app.test_client()

    pages = {  # output file -> app path
        "index.html": "/history?days=180", "history-30.html": "/history?days=30", "history-90.html": "/history?days=90",
        "history-365.html": "/history?days=365", "dashboard.html": "/dashboard", "api-access.html": "/api-access",
    }
    with app.app_context():
        from nimbus_app import history
        from nimbus_app.db import connect
        from datetime import date
        con = connect(app.config["DB_PATH"])
        rows = con.execute("SELECT MIN(day), MAX(day) FROM daily_states").fetchone()
        ov = history.overview(con, app.config["RULES"], date.fromisoformat(rows[0]), date.fromisoformat(rows[1]))
    to = rows[1]
    frm = (date.fromisoformat(to).toordinal() - 29)
    frm = date.fromordinal(frm).isoformat()
    pages["reports.html"] = f"/reports?from={frm}&to={to}"
    reports = {(frm, to): "reports.html"}
    for o in ov["outages"]:
        key = (o["start"][:10], o["end"][:10])
        if key not in reports:
            reports[key] = f"reports-{key[0]}.html"
            pages[reports[key]] = f"/reports?from={key[0]}&to={key[1]}"

    def link(m):
        attr, raw = m.group(1), html.unescape(m.group(2))
        u = urlparse(raw)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if raw.startswith(("http", "#", "mailto:")):
            return m.group(0)
        if u.path == "/shared/dashboard.css": return f'{attr}="dashboard.css"'
        if u.path == "/shared/dashboard.js": return f'{attr}="dashboard.js"'
        if u.path.startswith("/static/"): return f'{attr}="{u.path.rsplit("/", 1)[1]}"'
        if u.path == "/dashboard/status.json": return f'{attr}="status.json"'
        if u.path == "/dashboard": return f'{attr}="dashboard.html"'
        if u.path == "/history":
            d = q.get("days", "180")
            return f'{attr}="{"index.html" if d == "180" else f"history-{d}.html"}"'
        if u.path == "/reports" and (q.get("from"), q.get("to")) in reports:
            return f'{attr}="{reports[(q["from"], q["to"])]}"'
        if u.path == "/reports" and not q: return f'{attr}="reports.html"'
        if u.path in ("/", "/sign-in"): return f'{attr}="landing.html"'
        if u.path == "/api-access": return f'{attr}="api-access.html"'
        return f'{attr}="#" data-off'

    def clean(body: str) -> str:
        body = re.sub(r'(href|src|data-src|action)="([^"]*)"', link, body)
        body = re.sub(r'<a href="#" data-off\s*>Admin</a>', "", body)
        body = body.replace("live data starts 8 November 2026.</div>",
                            "live data starts 8 November 2026. Static preview: forms and downloads work in the live app.</div>")
        body = body.replace("</body>", '<script src="static.js"></script>\n</body>')
        body = body.replace('<link rel="stylesheet" href="app.css">', '<link rel="stylesheet" href="app.css">\n<link rel="stylesheet" href="static.css">')
        return body

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    written = []
    for name, path in pages.items():
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code)
        (out / name).write_text(clean(r.get_data(as_text=True)))
        written.append(name)
    r = anon.get("/")
    (out / "landing.html").write_text(clean(r.get_data(as_text=True)))
    written.append("landing.html")
    (out / "status.json").write_bytes(c.get("/dashboard/status.json").get_data())
    shutil.copy(APP.parent / "docs" / "dashboard.css", out / "dashboard.css")
    shutil.copy(APP.parent / "docs" / "dashboard.js", out / "dashboard.js")
    shutil.copy(APP / "nimbus_app" / "static" / "app.css", out / "app.css")
    (out / "static.js").write_text(STATIC_JS)
    (out / "static.css").write_text(STATIC_CSS)

    # index.html becomes the published page: drop the document wrapper the Artifact host adds itself
    idx = (out / "index.html").read_text()
    head = re.search(r"<head>(.*?)</head>", idx, re.S).group(1)
    head = re.sub(r'<meta charset="utf-8">\s*|<meta name="viewport"[^>]*>\s*', "", head)
    head = head.replace("<title>History · Nimbus Index</title>", "<title>Nimbus Index Preview</title>")
    body = re.search(r"<body>(.*)</body>", idx, re.S).group(1)
    (out / "index.html").write_text(head.strip() + "\n" + body.strip() + "\n")
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    print(build(Path(ap.parse_args().out)))
