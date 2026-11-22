"""Copy guard: fail if published copy contains a banned marketing phrase.

  python3 scripts/copy_guard.py site [templates/public templates/email ...]

Checks the visible text (plus alt, title, aria-label, aria-description, placeholder, value, data-label and meta
content) of every .html and .svg file, and the raw text of .txt and .md files, under each folder against
copy/banned.txt. Text is NFKC-normalised, soft hyphens and zero-width characters are dropped and Unicode dashes become
"-" before matching, so "real‑time" or "moni&shy;toring" are still caught.

The Methodology page (exactly <site root>/methodology/index.html, the site root being the nearest folder named
"site") is checked against the same list after the reviewed method-description phrases in
copy/methodology-allow.txt are removed, so it may describe the method as designed but nothing more.

Exits 1 and names each file and phrase on failure; 2 when the guard cannot run (missing folder, missing or empty
banned list, bad pattern). Standard library only: publish_site.sh runs it on the server with the system python3
before anything is published.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Pattern, Tuple

ROOT = Path(__file__).resolve().parent.parent
BANNED = ROOT / "copy" / "banned.txt"
ALLOW = ROOT / "copy" / "methodology-allow.txt"
TEXT_SUFFIXES = {".html", ".htm", ".svg", ".txt", ".md"}
MARKUP_SUFFIXES = {".html", ".htm", ".svg"}
TEXT_ATTRS = {"alt", "title", "aria-label", "aria-description", "placeholder", "content", "value", "data-label"}
METHODOLOGY_PAGE = ("methodology", "index.html")      # the one page that gets the allow-list, relative to site/
INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠"))   # soft hyphen and zero-width characters
HYPHENS = {**{c: "-" for c in range(0x2010, 0x2016)}, 0x2212: "-"}     # U+2010..U+2015 dashes, U+2212 minus
QUOTES = {0x2018: "'", 0x2019: "'"}


class ListError(Exception):
    """A pattern list is missing, empty or invalid: the guard cannot run."""


def load_patterns(path: Path, required: bool = True) -> List[Pattern[str]]:
    if not path.is_file():
        raise ListError(f"copy guard: missing list {path}")
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(re.compile(line, re.IGNORECASE))
        except re.error as e:
            raise ListError(f"copy guard: {path}:{n}: bad pattern {line!r}: {e}")
    if required and not out:
        raise ListError(f"copy guard: no banned patterns loaded from {path}")
    return out


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1
        for name, value in attrs:
            if name in TEXT_ATTRS and value:
                self.parts.append(" " + value + " ")
        # block boundaries so words from adjacent elements never run together
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self._skip:
            self._skip -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def normalise(text: str) -> str:
    """NFKC, drop soft hyphens and zero-width characters, plain hyphens and quotes, single spaces."""
    text = unicodedata.normalize("NFKC", text).translate(INVISIBLE).translate(HYPHENS).translate(QUOTES)
    return re.sub(r"\s+", " ", text)


def visible_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in MARKUP_SUFFIXES:
        p = _Text()
        p.feed(raw)
        p.close()
        raw = "".join(p.parts)
    return normalise(raw)


def is_methodology(path: Path) -> bool:
    """True only for <site root>/methodology/index.html."""
    path = path.resolve()
    for parent in path.parents:
        if parent.name == "site":
            return path.relative_to(parent).parts == METHODOLOGY_PAGE
    return False


def check_file(path: Path, banned: List[Pattern[str]], allow: List[Pattern[str]]) -> List[Tuple[str, str]]:
    """[(matched phrase, pattern)] for every banned phrase in the file."""
    text = visible_text(path)
    if is_methodology(path):
        for a in allow:
            text = a.sub(" ", text)
    hits = []
    for pat in banned:
        for m in pat.finditer(text):
            hits.append((m.group(0), pat.pattern))
    return hits


def check_dirs(dirs: List[Path], banned_file: Path = BANNED, allow_file: Path = ALLOW) -> Tuple[int, List[str]]:
    """(files checked, failure lines). Raises ListError if the lists cannot be loaded."""
    banned, allow = load_patterns(banned_file), load_patterns(allow_file, required=False)
    checked, failures = 0, []
    for d in dirs:
        files = [d] if d.is_file() else sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
        for f in files:
            checked += 1
            for phrase, pattern in check_file(f, banned, allow):
                failures.append(f'{f}: banned phrase "{phrase}" (rule: {pattern})')
    return checked, failures


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dirs", nargs="+", type=Path, help="folders (or files) to check")
    ap.add_argument("--banned", type=Path, default=BANNED)
    ap.add_argument("--allow", type=Path, default=ALLOW)
    args = ap.parse_args(argv)
    missing = [str(d) for d in args.dirs if not d.exists()]
    if missing:
        print(f"copy guard: not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        checked, failures = check_dirs(args.dirs, args.banned, args.allow)
    except ListError as e:
        print(str(e), file=sys.stderr)
        return 2
    if failures:
        print(f"copy guard: {len(failures)} banned phrase(s) found:", file=sys.stderr)
        for line in failures:
            print("  " + line, file=sys.stderr)
        return 1
    print(f"copy guard: {checked} file(s) checked, no banned phrases")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:                      # the guard crashed: exit 2, never 1 (1 means a banned phrase)
        print(f"copy guard: could not run: {type(e).__name__}: {e}", file=sys.stderr)
        code = 2
    sys.exit(code)
