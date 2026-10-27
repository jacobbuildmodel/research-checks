"""Unit tests for tools/: each builds a throwaway git repository, runs a tool in
it as a subprocess, and checks the exit code and the lines it prints.

    python3 -m unittest discover -s tests -v
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def review(thesis_text, verdict="GO", **over):
    fields = {"principles": "v1", "piece": "p", "repo": "r", "ref": "main", "reviewed": "THESIS.md",
              "reviewed_md5": md5(thesis_text), "stage": "seal", "date": "2026-10-28", "reviewer": "t",
              "G0": "PASS", "G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": "PASS", "G5": "PASS",
              "headline_yes": "yes it does", "headline_no": "no it does not", "verdict": verdict,
              "p_zero_cell": "0.2", "smallest_effect": "1", "positive_control": "x",
              "kill_criteria": "y", "decision_date": "2026-12-01"}
    fields.update(over)
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in fields.items()) + "---\n\nbody\n"


class Repo:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="rc-test-")
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args):
        r = subprocess.run(["git", *args], cwd=self.dir, capture_output=True, text=True,
                           env={**os.environ, **GIT_ENV})
        if r.returncode:
            raise RuntimeError(r.stderr)
        return r.stdout.strip()

    def write(self, path, text):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full) or self.dir, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def commit(self, msg, files):
        for path, text in files.items():
            self.write(path, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run(self, tool, *args):
        r = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, tool), *args], cwd=self.dir,
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


THESIS = "# THESIS\n\nT1: the number is 42.\n"


def manifest(files):
    body = "".join(f"{md5(text)}  {name}\n" for name, text in files.items())
    return f"# SEAL MANIFEST\n\n```\n{body}```\n"


CONFIG = textwrap.dedent("""\
    [pieces.p]
    dir = "p"
    [pieces.p.seal]
    kind = "manifest"
    thesis = "strict"
    """)


class PurposeGate(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.r.commit("start", {"README": "x\n"})
        fd, self.exempt = tempfile.mkstemp(prefix="rc-exempt-", suffix=".txt")
        with os.fdopen(fd, "w") as f:
            f.write("# repository commit path why\n")

    def tearDown(self):
        os.remove(self.exempt)
        self.r.close()

    def gate(self):
        return self.r.run("seal_check.py", "purpose", "--repo", "r", "--exempt", self.exempt)

    def test_no_marker_passes(self):
        code, out = self.gate()
        self.assertEqual(code, 0, out)
        self.assertIn("no seal marker has ever been added", out)

    def test_seal_without_review_fails(self):
        self.r.commit("seal", {"p/THESIS.md": THESIS, "p/SEALED": "sealed\n"})
        code, out = self.gate()
        self.assertEqual(code, 1, out)
        self.assertIn("no p/PURPOSE_REVIEW.md in that commit", out)

    def test_seal_with_valid_review_passes(self):
        self.r.commit("seal", {"p/THESIS.md": THESIS, "p/PURPOSE_REVIEW.md": review(THESIS), "p/SEAL_MANIFEST.md": manifest({"THESIS.md": THESIS})})
        code, out = self.gate()
        self.assertEqual(code, 0, out)
        self.assertIn("verdict GO", out)

    def test_paper_track_passes_and_stop_fails(self):
        self.r.commit("seal a", {"a/THESIS.md": THESIS, "a/PURPOSE_REVIEW.md": review(THESIS, "PAPER TRACK", G3="WEAK"), "a/SEALED": "s\n"})
        code, out = self.gate()
        self.assertEqual(code, 0, out)
        self.r.commit("seal b", {"b/THESIS.md": THESIS, "b/PURPOSE_REVIEW.md": review(THESIS, "STOP"), "b/SEALED": "s\n"})
        code, out = self.gate()
        self.assertEqual(code, 1, out)
        self.assertIn("verdict STOP does not allow a seal", out)

    def test_review_of_another_thesis_fails(self):
        self.r.commit("seal", {"p/THESIS.md": THESIS, "p/PURPOSE_REVIEW.md": review("an earlier draft\n"), "p/SEALED": "s\n"})
        code, out = self.gate()
        self.assertEqual(code, 1, out)
        self.assertIn("!= md5 of the THESIS.md being sealed", out)

    def test_header_rules_are_enforced(self):
        self.r.commit("seal", {"p/THESIS.md": THESIS, "p/PURPOSE_REVIEW.md": review(THESIS, G3="WEAK"), "p/SEALED": "s\n"})
        code, out = self.gate()
        self.assertEqual(code, 1, out)
        self.assertIn("GO needs G3 PASS", out)

    def test_review_added_after_the_seal_does_not_count(self):
        self.r.commit("seal", {"p/THESIS.md": THESIS, "p/SEALED": "s\n"})
        self.r.commit("review later", {"p/PURPOSE_REVIEW.md": review(THESIS)})
        code, out = self.gate()
        self.assertEqual(code, 1, out)

    def test_record_marker_at_root_and_exempt_list(self):
        sha = self.r.commit("record", {"THESIS.md": THESIS, "office/SEAL.txt": "Seal commit abc\n"})
        code, out = self.gate()
        self.assertEqual(code, 1, out)
        self.assertIn("no PURPOSE_REVIEW.md in that commit", out)
        with open(self.exempt, "a") as f:
            f.write(f"r  {sha}  office/SEAL.txt  sealed before the gate\n")
        code, out = self.gate()
        self.assertEqual(code, 0, out)
        self.assertIn("exempt", out)


class SealIntegrity(unittest.TestCase):
    def setUp(self):
        self.r = Repo()
        self.files = {"THESIS.md": THESIS, "11_tests.py": "print(42)\n", "12_figures.py": "print('fig')\n"}
        self.r.commit("draft", {f"p/{k}": v for k, v in self.files.items()})
        self.seal = self.r.commit("seal", {"p/SEAL_MANIFEST.md": manifest(self.files)})
        self.r.commit("open data", {"p/SEALED": f"THESIS.md sealed at {self.seal[:7]}.\n"})

    def tearDown(self):
        self.r.close()

    def check(self, config=CONFIG):
        self.r.write(".github/research-checks.toml", config)
        return self.r.run("seal_check.py", "piece", "p")

    def test_intact_seal_passes(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("SEALED names the same commit", out)
        self.assertIn("3 sealed files: 3 match HEAD", out)

    def test_changed_thesis_fails(self):
        self.r.commit("edit", {"p/THESIS.md": THESIS + "one more line\n"})
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("p/THESIS.md changed since the seal", out)

    def test_append_mode_allows_appended_amendments_only(self):
        cfg = CONFIG.replace('thesis = "strict"', 'thesis = "append"')
        self.r.commit("amend", {"p/THESIS.md": THESIS + "\n## AMENDMENT 1\n"})
        # The manifest's THESIS line is still the sealed text, so only the THESIS rule is in play.
        code, out = self.check(cfg)
        self.assertIn("amendments appended below it", out)
        self.r.commit("rewrite", {"p/THESIS.md": THESIS.replace("42", "43") + "\n## AMENDMENT 1\n"})
        code, out = self.check(cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("changed above the sealed text", out)

    def test_undeclared_drift_fails(self):
        self.r.commit("figs", {"p/12_figures.py": "print('better fig')\n"})
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("12_figures.py: sealed", out)
        self.assertIn("not declared", out)

    def test_declared_drift_needs_the_addendum(self):
        new = "print('better fig')\n"
        self.r.commit("figs", {"p/12_figures.py": new})
        cfg = CONFIG + textwrap.dedent(f"""\
            drift = [
              {{ path = "12_figures.py", sealed_md5 = "{md5(self.files['12_figures.py'])}", why = "addendum item 1" }},
            ]
            """)
        code, out = self.check(cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("is not recorded in p/THESIS_ADDENDUM.md", out)
        self.r.commit("addendum", {"p/THESIS_ADDENDUM.md": f"## 1. 12_figures.py\n\nmd5 now {md5(new)}\n"})
        code, out = self.check(cfg)
        self.assertEqual(code, 0, out)
        self.assertIn("CHANGED AFTER SEAL, declared", out)

    def test_thesis_can_never_be_declared(self):
        cfg = CONFIG + f'drift = [{{ path = "THESIS.md", sealed_md5 = "{md5(THESIS)}", why = "no" }}]\n'
        code, out = self.check(cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("THESIS.md can never change after the seal", out)

    def test_stale_declaration_fails(self):
        cfg = CONFIG + f'drift = [{{ path = "11_tests.py", sealed_md5 = "{md5("print(42)" + chr(10))}", why = "x" }}]\n'
        code, out = self.check(cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("remove the stale declaration", out)

    def test_missing_sealed_marker_fails(self):
        self.r.git("rm", "-q", "p/SEALED")
        self.r.git("commit", "-q", "-m", "drop")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("p/SEALED is not present at HEAD", out)

    def test_changed_manifest_fails(self):
        self.r.commit("touch", {"p/SEAL_MANIFEST.md": manifest(self.files) + "\n"})
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("SEAL_MANIFEST.md changed since the seal commit", out)

    def test_record_kind(self):
        r = Repo()
        try:
            seal = r.commit("seal", {"q/THESIS.md": THESIS})
            r.commit("record", {"q/office/SEAL.txt": f"Seal commit  {seal}\nmd5 of q/THESIS.md at the seal commit: {md5(THESIS)}\n"})
            r.write(".github/research-checks.toml", '[pieces.q]\ndir = "q"\n[pieces.q.seal]\nkind = "record"\n')
            code, out = r.run("seal_check.py", "piece", "q")
            self.assertEqual(code, 0, out)
            self.assertIn("has the recorded md5", out)
            r.commit("edit", {"q/THESIS.md": THESIS + "x\n"})
            code, out = r.run("seal_check.py", "piece", "q")
            self.assertEqual(code, 1, out)
        finally:
            r.close()

    def test_header_kind_needs_a_commit(self):
        r = Repo()
        try:
            seal = r.commit("seal", {"THESIS.md": THESIS})
            r.write(".github/research-checks.toml", '[pieces.root]\ndir = "."\n[pieces.root.seal]\nkind = "header"\n')
            code, out = r.run("seal_check.py", "piece", "root")
            self.assertEqual(code, 1, out)
            self.assertIn("no seal commit in the configuration", out)
            r.write(".github/research-checks.toml", '[pieces.root]\ndir = "."\n[pieces.root.seal]\n'
                    f'kind = "header"\ncommit = "{seal}"\nwhy = "first commit"\nrecorded_md5 = "{md5(THESIS)}"\n')
            code, out = r.run("seal_check.py", "piece", "root")
            self.assertEqual(code, 0, out)
        finally:
            r.close()


class Standards(unittest.TestCase):
    def setUp(self):
        self.r = Repo()

    def tearDown(self):
        self.r.close()

    def test_clean_piece_passes(self):
        # raw/.gitattributes is not data: check.sh's raw/* glob skips hidden files
        self.r.commit("p", {"p/a.py": "import os\nimport pandas\n", "p/requirements.txt": "pandas==3.0.2\n",
                            "p/raw/x.csv": "1\n", "p/raw/RETRIEVED.txt": "x.csv from somewhere\n",
                            "p/raw/.gitattributes": "* -text\n"})
        code, out = self.r.run("standards_fast.py", "--dir", "p")
        self.assertEqual(code, 0, out)
        self.assertIn("ALL CHECKS PASSED", out)

    def test_failures_are_found(self):
        article = '---\ntitle: "' + "A" * 61 + '"\n---\nwe ' + "word " * 100 + "you should buy\n"
        self.r.commit("p", {"p/2026-10-31.md": article, "p/a.py": "import requests\n", "p/requirements.txt": "pandas>=2\n", "p/note.md": "caf\u00e9\n", "p/raw/x.csv": "1\n", "p/raw/RETRIEVED.txt": "nothing\n"})
        code, out = self.r.run("standards_fast.py", "--dir", "p")
        self.assertEqual(code, 1, out)
        for s in ("FAIL  non-ASCII found", "FAIL  advice language", "FAIL  royal we",
                  "headline 61 chars, over 60", "words, outside 1200-1800", "FAIL  undeclared imports",
                  "FAIL  unpinned dependencies", "p/raw/x.csv not recorded"):
            self.assertIn(s, out)

    def test_warn_skip_and_exclude_from_config(self):
        self.r.commit("p", {"p/fonts/LICENSE.md": "\u00a9 font\n", "p/requirements.txt": "pandas>=2\n", "p/raw/x.csv": "1\n"})
        self.r.write(".github/research-checks.toml", textwrap.dedent("""\
            [pieces.p]
            dir = "p"
            [pieces.p.standards]
            exclude = { "fonts/" = "vendored font licence" }
            warn = { pinned = "reported to the moderator" }
            skip = { provenance = "raw/ is a fixture" }
            """))
        code, out = self.r.run("standards_fast.py", "--piece", "p")
        self.assertEqual(code, 0, out)
        self.assertIn("pass  no non-ASCII in tracked text", out)
        self.assertIn("WARN  unpinned dependencies", out)
        self.assertIn("WARN  pinned: reported, not blocking (reported to the moderator)", out)
        self.assertIn("skip  provenance: raw/ is a fixture", out)

    def test_reasons_are_required(self):
        self.r.commit("p", {"p/a.py": "x = 1\n"})
        self.r.write(".github/research-checks.toml", '[pieces.p]\ndir = "p"\n[pieces.p.standards]\nskip = { ascii = " " }\n')
        code, out = self.r.run("standards_fast.py", "--piece", "p")
        self.assertNotEqual(code, 0, out)
        self.assertIn("gives no reason", out)


class Matrix(unittest.TestCase):
    def test_rows_carry_tier_keys(self):
        r = Repo()
        try:
            r.write(".github/research-checks.toml", '[pieces.a]\ndir = "a/"\n[pieces.a.fast]\ntests = "a/tests"\n'
                    '[pieces.b]\ndir = "."\n[pieces.b.seal]\nkind = "header"\n')
            code, out = r.run("rc.py", "pieces", "fast")
            self.assertEqual(code, 0, out)
            self.assertEqual(out.strip(), '[{"name": "a", "dir": "a", "python": "3.11", "requirements": "", '
                                          '"tests": "a/tests", "manifest": ""}]')
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main()
