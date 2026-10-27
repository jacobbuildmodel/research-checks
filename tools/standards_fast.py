"""Tier (iii): the fast half of hdb-affordability's check.sh (the machine-checkable
half of STANDARDS v2), ported to Python and parameterised per piece.

  python3 standards_fast.py --piece <name> [--config PATH] [--plain]
  python3 standards_fast.py --dir <dir> [--length-exempt FILE ...]

Run from the repository root. For a piece at the root (dir "."), with the same
length exemptions and no skip, warn or exclude, the output is line for line
the output of `./check.sh` in fast mode, so the two can be diffed until the
port is trusted (hdb-affordability's standards workflow does exactly that).
For a piece in a subdirectory every file set below is the same set restricted
to that directory:

  ascii       F5   no non-ASCII byte in tracked .md .py .sh .txt .csv (raw/ excluded)
  advice      F3   no advice language in articles (files named YYYY-MM-DD.md)
  we          F3   no "we" in articles
  headline    F5   article title at most 60 characters
  length      F6   article body 1200-1800 words, unless exempt
  svg_dark    E1   every tracked .svg has a prefers-color-scheme block
  svg_390     E2   smallest text at least 11px when the chart is 390px wide
  imports     A6   requirements.txt covers every import
  pinned      A6   every requirement pinned with ==
  provenance  C1   every file in raw/ named in raw/RETRIEVED.txt

Configuration, [pieces.<name>.standards], every entry with its reason:
  length_exempt = ["2026-09-12.md"]                  # paths relative to the piece
  exclude = { "fonts/" = "vendored font licences" }  # path prefixes left out of every file set
  warn = { length = "why this is reported, not blocking" }
  skip = { provenance = "why this check does not apply" }

A warned check still runs and prints each finding as WARN, every run; a
skipped check prints its reason. Neither passes silently.
"""
import ast
import glob
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/ itself, also under python -I
import rc  # noqa: E402

CHECKS = ("ascii", "advice", "we", "headline", "length", "svg_dark", "svg_390", "imports", "pinned", "provenance")
ADVICE = re.compile(r"\b(you should|should buy|recommend|better option|price target|buy the|sell the)\b", re.I)
WE = re.compile(r"\bwe\b")
ARTICLE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$")
TITLE = re.compile(r'^title: *"(.*)"')


class Out:
    def __init__(self, warn, skip):
        self.warn, self.skip = warn, skip
        self.failed = False
        self.warned = set()

    def ok(self, s):
        print(f"pass  {s}")

    def fail(self, check, s):
        if check in self.warn:
            print(f"WARN  {s}")
            self.warned.add(check)
        else:
            print(f"FAIL  {s}")
            self.failed = True

    def runs(self, check):
        """False, after printing the reason, when the configuration skips this check."""
        if check in self.skip:
            print(f"skip  {check}: {self.skip[check]}")
            return False
        return True


def rel(d, f):
    return f if d == "." else f[len(d) + 1:]


def tracked(d, exclude, *exts):
    files = subprocess.run(["git", "ls-files", *[f"*{e}" for e in exts]], capture_output=True,
                           text=True, encoding="utf-8").stdout.splitlines()
    if d != ".":
        files = [f for f in files if f.startswith(d + "/")]
    return [f for f in files if not any(rel(d, f).startswith(x) for x in exclude)]


def grep_lines(files, pred):
    """grep -n output: 'file:line:text', or 'line:text' when given one file (as grep prints)."""
    hits = []
    for f in files:
        for i, raw in enumerate(open(f, "rb").read().split(b"\n"), 1):
            if pred(raw):
                text = raw.decode("utf-8", errors="replace")
                hits.append(f"{i}:{text}" if len(files) == 1 else f"{f}:{i}:{text}")
    return hits


def word_count(path):
    t = open(path, encoding="utf-8").read()
    if t.startswith("---"):
        t = t.split("---", 2)[2] if t.count("---") >= 2 else t
    t = re.sub(r"\{\{<\s*aside.*?\{\{<\s*/aside\s*>\}\}", " ", t, flags=re.S)
    t = re.sub(r"\{\{<[^>]*>\}\}", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    return len(t.split())


def svg_390(p):
    """(line to print, too small?) as check.sh's inline Python prints and exits."""
    s = open(p, encoding="utf-8", errors="replace").read()
    m = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', s)
    sizes = [float(x) for x in re.findall(r'font-size[:=]"?\s*([\d.]+)', s)]
    if not m or not sizes:
        return "      (no viewBox or no font-size found in %s)" % p, False
    smallest = min(sizes) * (390.0 / float(m.group(1)))
    return "      %s smallest rendered text at 390px: %.1fpx" % (p, smallest), smallest < 11.0


def base(d):
    return "" if d == "." else d + "/"


def req_files(d):
    return sorted(glob.glob(base(d) + "requirements.txt") + glob.glob(base(d) + "*/requirements.txt"))


def undeclared_imports(d, exclude):
    std = set(sys.stdlib_module_names)
    req = set()
    for f in req_files(d):
        for line in open(f, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if line:
                req.add(re.split(r"[<>=!\[]", line)[0].lower().replace("-", "_"))
    missing = set()
    for f in glob.glob(base(d) + "*.py") + glob.glob(base(d) + "*/*.py"):
        f = f.replace(os.sep, "/")
        if any(rel(d, f).startswith(x) for x in exclude):
            continue
        try:
            t = ast.parse(open(f, encoding="utf-8").read())
        except SyntaxError:
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.Import):
                mods = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods = [n.module.split(".")[0]]
            else:
                continue
            for m in mods:
                if m in std or m in req:
                    continue
                # A local module: at the root or beside the importing file (as check.sh), or at
                # the top of the piece (a piece's tests import its library from one level up).
                if any(os.path.exists(os.path.join(x, m + ".py")) for x in ("", os.path.dirname(f), base(d))):
                    continue
                missing.add((f, m))
    return sorted(missing)


def run(d, length_exempt=(), skip=None, warn=None, exclude=()):
    o = Out(warn or {}, skip or {})
    text = [f for f in tracked(d, exclude, ".md", ".py", ".sh", ".txt", ".csv") if not rel(d, f).startswith("raw/")]
    articles = [f for f in tracked(d, exclude, ".md") if ARTICLE.search(f)]
    svgs = tracked(d, exclude, ".svg")

    print("== F5 pure ASCII")
    if o.runs("ascii"):
        bad = grep_lines(text, lambda b: any(c > 0x7F for c in b))[:20]
        if not bad:
            o.ok("no non-ASCII in tracked text")
        else:
            o.fail("ascii", "non-ASCII found")
            print("\n".join(bad))

    print("== F3 banned words, articles only")
    if articles:
        for check, rx, good, badname in (("advice", ADVICE, "no advice language", "advice language"),
                                         ("we", WE, "no royal we", "royal we")):
            if not o.runs(check):
                continue
            bad = grep_lines(articles, lambda b: rx.search(b.decode("utf-8", errors="replace")))
            if not bad:
                o.ok(good)
            else:
                o.fail(check, badname)
                print("\n".join(bad))

    print("== F5/F6 headline and length")
    if articles:
        do_headline, do_length = o.runs("headline"), o.runs("length")
    for a in articles:
        if do_headline:
            t = next((TITLE.sub(r"\1", line, count=1) for line in
                      open(a, encoding="utf-8", errors="replace").read().split("\n") if TITLE.match(line)), None)
            if t:
                if len(t) <= 60:
                    o.ok(f"{a} headline {len(t)} chars")
                else:
                    o.fail("headline", f"{a} headline {len(t)} chars, over 60")
        if rel(d, a) in length_exempt:
            o.ok(f"{a} exempt from the length rule")
            continue
        if do_length:
            w = word_count(a)
            if w < 1200 or w > 1800:
                o.fail("length", f"{a} {w} words, outside 1200-1800")
            else:
                o.ok(f"{a} {w} words")

    print("== E1/E2 charts: dark mode block and 390px legibility")
    if svgs:
        do_dark, do_390 = o.runs("svg_dark"), o.runs("svg_390")
    for s in svgs:
        if do_dark and "prefers-color-scheme" not in open(s, encoding="utf-8", errors="replace").read():
            o.fail("svg_dark", f"{s} has no prefers-color-scheme block")
        if do_390:
            msg, small = svg_390(s)
            print(msg)
            if small:
                o.fail("svg_390", f"{s} text under 11px at 390px")

    print("== A6 requirements cover every import")
    if o.runs("imports"):
        missing = undeclared_imports(d, exclude)
        for f, m in missing:
            print("      undeclared import %s in %s" % (m, f))
        if not missing:
            o.ok("requirements cover every import")
        else:
            o.fail("imports", "undeclared imports")

    print("== A6 versions pinned")
    if o.runs("pinned"):
        unpinned = [w for f in req_files(d) for line in open(f, encoding="utf-8").read().split("\n")
                    if re.match(r"[A-Za-z]", line) and "==" not in line for w in line.split()]
        if not unpinned:
            o.ok("all versions pinned")
        else:
            o.fail("pinned", "unpinned dependencies")
            for u in unpinned:
                print(f"      {u}")

    print("== C1 provenance recorded")
    raw = base(d) + "raw"
    if os.path.isdir(raw) and o.runs("provenance"):
        if os.path.isfile(raw + "/RETRIEVED.txt"):
            record = open(raw + "/RETRIEVED.txt", encoding="utf-8", errors="replace").read()
            # check.sh's raw/* glob: hidden files (raw/.gitattributes) are not data
            miss = [b for b in sorted(os.listdir(raw))
                    if b != "RETRIEVED.txt" and not b.startswith(".") and b not in record]
            for b in miss:
                o.fail("provenance", f"{raw}/{b} not recorded in RETRIEVED.txt")
            if not miss:
                o.ok("every raw file recorded")
        else:
            o.fail("provenance", f"{raw}/ exists but RETRIEVED.txt does not")

    print()
    for check in sorted(o.warned):
        print(f"WARN  {check}: reported, not blocking ({o.warn[check]})")
    if o.failed:
        print("CHECKS FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


def main(argv):
    config = argv[argv.index("--config") + 1] if "--config" in argv else rc.CONFIG
    if "--piece" in argv:
        name = argv[argv.index("--piece") + 1]
        p = rc.load(config)["pieces"].get(name)
        if p is None or "standards" not in p:
            raise SystemExit(f"config: no [pieces.{name}.standards]")
        s = p["standards"]
        for key in ("skip", "warn"):
            for c, why in s.get(key, {}).items():
                if c not in CHECKS:
                    raise SystemExit(f"config: unknown check {c!r} in {key} (one of {', '.join(CHECKS)})")
                if not why.strip():
                    raise SystemExit(f"config: {key}.{c} gives no reason")
        if "--plain" in argv:  # for the parity diff: check.sh's own settings only, no header
            return run(p["dir"], s.get("length_exempt", []))
        for x, why in s.get("exclude", {}).items():
            print(f"excluded from every file set: {base(p['dir'])}{x} ({why})")
        print(f"standards (fast half of check.sh): piece {name}, {p['dir']}/")
        return run(p["dir"], s.get("length_exempt", []), s.get("skip", {}), s.get("warn", {}),
                   tuple(s.get("exclude", {})))
    if "--dir" in argv:
        d = argv[argv.index("--dir") + 1].strip("/") or "."
        ex = argv[argv.index("--length-exempt") + 1:] if "--length-exempt" in argv else []
        return run(d, ex)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
