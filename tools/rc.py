"""Shared helpers for the research-checks tools: the caller's configuration,
git reads of committed blobs, and the pass/FAIL printer.

The configuration lives in the calling repository, by default at
.github/research-checks.toml. One [pieces.<name>] table per piece; a piece
takes part in a tier when it has that tier's sub-table:

    [pieces.pwm]
    dir = "pwm"                         # "." for a piece at the repository root
    python = "3.11"                     # optional, default 3.11
    requirements = "pwm/requirements.txt"

    [pieces.pwm.seal]                   # tier (i), see seal_check.py
    [pieces.pwm.fast]                   # tier (ii): manifest --check, synthetic suite
    [pieces.pwm.standards]              # tier (iii), see standards_fast.py

Usage:  python3 rc.py pieces <tier> [--config PATH]
        prints, for a workflow matrix, a JSON list with one object per piece
        that takes part in <tier> (seal, fast, standards or rebuild): name,
        dir, python, requirements, and the tier table's own string values.
"""
import hashlib
import json
import os
import posixpath
import subprocess
import sys
import tomllib

CONFIG = ".github/research-checks.toml"
TIERS = ("seal", "fast", "standards", "rebuild")
# Keys each tier's workflow tests for; always present in its matrix rows ("" when unset).
TIER_KEYS = {"seal": (), "fast": ("tests", "manifest"), "standards": ("parity",), "rebuild": ("command", "clean")}


def load(path=CONFIG):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    pieces = cfg.get("pieces", {})
    for name, p in pieces.items():
        if "dir" not in p:
            raise SystemExit(f"config: piece {name} has no dir")
        p["name"] = name
        p["dir"] = p["dir"].strip("/") or "."
    return cfg


def pieces(cfg, tier):
    return [n for n, p in cfg.get("pieces", {}).items() if tier in p]


def matrix(cfg, tier):
    rows = []
    for n in pieces(cfg, tier):
        p = cfg["pieces"][n]
        row = {"name": n, "dir": p["dir"], "python": p.get("python", "3.11"),
               "requirements": p.get("requirements", "")}
        row.update({k: "" for k in TIER_KEYS[tier]})
        row.update({k: v for k, v in p[tier].items() if isinstance(v, str)})
        rows.append(row)
    return rows


def join(d, *parts):
    """Path inside piece directory d ("." is the repository root), posix style."""
    return posixpath.join(*parts) if d in (".", "") else posixpath.join(d, *parts)


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r


def out(*args):
    return git(*args).stdout.decode("utf-8", errors="replace")


def blob(rev, path):
    """Bytes of path as committed at rev, or None if it is not there."""
    r = git("cat-file", "blob", f"{rev}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def resolve(rev):
    r = git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def is_ancestor(a, b):
    return git("merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def require_full_history():
    if out("rev-parse", "--is-shallow-repository").strip() == "true":
        raise SystemExit("FAIL  the clone is shallow; check out with fetch-depth: 0")


def md5(b):
    return hashlib.md5(b).hexdigest()


class Report:
    """Prints check.sh-style lines and counts failures."""

    def __init__(self):
        self.failed = 0

    def section(self, s):
        print(f"== {s}")

    def ok(self, s):
        print(f"pass  {s}")

    def note(self, s):
        print(f"      {s}")

    def fail(self, s):
        print(f"FAIL  {s}")
        self.failed += 1

    def finish(self, what):
        print()
        if self.failed:
            print(f"{what}: {self.failed} FAILED")
            return 1
        print(f"{what}: ALL CHECKS PASSED")
        return 0


def main(argv):
    if len(argv) >= 3 and argv[1] == "pieces" and argv[2] in TIERS:
        path = argv[argv.index("--config") + 1] if "--config" in argv else CONFIG
        if not os.path.exists(path):
            raise SystemExit(f"no configuration at {path}")
        print(json.dumps(matrix(load(path), argv[2])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
