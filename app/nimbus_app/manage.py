"""Command line for the server.

  python -m nimbus_app.manage sync                      fetch the data branch and count new results
  python -m nimbus_app.manage invite EMAIL [--admin] [--name N] [--company C]
                                                        print a single-use invite link (7 days)
  python -m nimbus_app.manage backup FILE               consistent copy of the database
  python -m nimbus_app.manage rollup [--all]            rebuild the daily roll-ups (all days, or the ones due)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from . import create_app, mirror


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="nimbus_app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    p = sub.add_parser("invite")
    p.add_argument("email")
    p.add_argument("--admin", action="store_true")
    p.add_argument("--name", default="")
    p.add_argument("--company", default="")
    p = sub.add_parser("backup")
    p.add_argument("file")
    p = sub.add_parser("rollup")
    p.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    app = create_app()
    c = app.config
    if a.cmd == "sync":
        print(mirror.sync(c["DATA_DIR"], c["DB_PATH"], c["DATA_REMOTE"], c["RULES"]))
    elif a.cmd == "invite":
        from . import auth
        with app.test_request_context(base_url=c["BASE_URL"]):
            from flask import url_for
            from .db import get_db
            if get_db().execute("SELECT 1 FROM users WHERE email = ?", (a.email,)).fetchone():
                sys.exit(f"{a.email} already has an account.")
            tok = auth.create_invite(a.email, a.name, a.company, "admin" if a.admin else "member")
            print(url_for("web.accept_invite", token=tok, _external=True))
    elif a.cmd == "rollup":
        from . import history
        from .db import connect
        con = connect(c["DB_PATH"])
        days = ([r[0] for r in con.execute("SELECT DISTINCT day FROM ingested_files")] if a.all
                else history.days_to_refresh(con))
        print(f"rolled up {history.rollup_days(con, c['RULES'], days)} days")
    elif a.cmd == "backup":
        src = sqlite3.connect(c["DB_PATH"])
        dst = sqlite3.connect(a.file)
        src.backup(dst)
        dst.close(); src.close()
        print(f"backed up to {a.file}")


if __name__ == "__main__":
    main()
