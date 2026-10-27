"""Tier (i): seal integrity, and the purpose gate on new seals.

Every comparison reads committed blobs (git cat-file), never the working copy.
Needs the full history (actions/checkout with fetch-depth: 0).

  python3 seal_check.py piece <name> [--config PATH]
      Seal integrity of one configured piece ([pieces.<name>.seal]):
        - the seal commit is found, and is an ancestor of HEAD;
        - THESIS.md at HEAD is the THESIS.md at the seal commit (thesis =
          "strict"), or that text with amendments appended below it and nothing
          above changed (thesis = "append", for pieces whose own rules allow
          appended, dated AMENDMENT blocks);
        - any md5 the piece's own seal record gives for THESIS.md matches;
        - kind = "manifest": SEALED is present, SEAL_MANIFEST.md is unchanged
          since the seal, and every md5 in it matches the file at HEAD. A file
          that has changed since the seal passes only if (a) the configuration
          declares it in `drift`, with the md5 the manifest gives it and a
          reason, and (b) the piece's THESIS_ADDENDUM.md records its md5 at
          HEAD (the pieces' own rule: a change after the seal is reported
          there, dated). THESIS.md can never be declared.
        - kind = "record": office/SEAL.txt is present and names the seal
          commit (and the THESIS.md md5, if it gives one).
        - kind = "header": the seal commit is given in the configuration
          (`commit`), or named in THESIS.md's header as "at commit `<sha>`".

  python3 seal_check.py purpose [--exempt EXEMPT_SEALS.txt] [--repo NAME]
      The purpose gate (office/PURPOSE_PRINCIPLES.md). Every commit in HEAD's
      history that ADDS a seal marker -- <piece>/SEALED, <piece>/SEAL_MANIFEST*,
      or <piece>/office/SEAL.txt -- fails unless, in that same commit,
      <piece>/PURPOSE_REVIEW.md exists, passes the header rules
      (purpose_header.py), has verdict GO or PAPER TRACK, and its reviewed_md5
      is the md5 of <piece>/THESIS.md as committed there. Seals made before the
      gate are listed in EXEMPT_SEALS.txt by repository, commit and path, and
      pass with a note. The gate needs no configuration, so a new piece is
      covered before anyone adds it to the config.
"""
import os
import posixpath
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # tools/ itself, also under python -I
import purpose_header  # noqa: E402
import rc  # noqa: E402

MARKER_HINT = "SEALED, SEAL_MANIFEST*, office/SEAL.txt"
SHA = r"[0-9a-f]{7,40}"


# ---------------------------------------------------------------- the purpose gate

def marker_piece(path):
    """The piece directory a newly added path seals, or None if it is not a seal marker."""
    base = posixpath.basename(path)
    if base == "SEALED" or base.startswith("SEAL_MANIFEST"):
        return posixpath.dirname(path)
    if path == "office/SEAL.txt" or path.endswith("/office/SEAL.txt"):
        return posixpath.dirname(posixpath.dirname(path))
    return None


def load_exempt(path):
    exempt = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        repo, sha, p, why = line.split(None, 3)
        exempt[(repo, sha, p)] = why
    return exempt


def added_markers():
    """(commit, path, piece) for every seal marker added in HEAD's history, oldest first."""
    found, commit = [], None
    for line in rc.out("log", "--reverse", "--diff-filter=A", "--name-only", "--format=@@%H", "HEAD").splitlines():
        if line.startswith("@@"):
            commit = line[2:]
        elif line.strip():
            piece = marker_piece(line.strip())
            if piece is not None:
                found.append((commit, line.strip(), piece))
    return found


def gate_one(commit, path, piece, R):
    review_path = rc.join(piece or ".", "PURPOSE_REVIEW.md")
    thesis_path = rc.join(piece or ".", "THESIS.md")
    where = f"{path} added in {commit[:12]}"
    review = rc.blob(commit, review_path)
    thesis = rc.blob(commit, thesis_path)
    if review is None:
        R.fail(f"{where}: no {review_path} in that commit (purpose gate: no seal without a GO or PAPER TRACK review)")
        return
    if thesis is None:
        R.fail(f"{where}: no {thesis_path} in that commit, so there is nothing the review can be checked against")
        return
    h, errs = purpose_header.validate(review.decode("utf-8", errors="replace"), rc.md5(thesis))
    if h is not None and not errs and h["verdict"] not in purpose_header.SEAL_VERDICTS:
        errs.append(f"verdict {h['verdict']} does not allow a seal (GO or PAPER TRACK needed)")
    if errs:
        R.fail(f"{where}: {review_path} " + "; ".join(errs))
    else:
        R.ok(f"{where}: {review_path} verdict {h['verdict']}, reviewed_md5 = md5 of {thesis_path} {rc.md5(thesis)}")


def purpose(exempt_path, repo):
    R = rc.Report()
    rc.require_full_history()
    exempt = load_exempt(exempt_path)
    R.section(f"purpose gate: commits in HEAD's history that add a seal marker ({MARKER_HINT})")
    markers = added_markers()
    if not markers:
        R.ok("no seal marker has ever been added in this history")
    seen = set()
    for commit, path, piece in markers:
        key = (repo, commit, path)
        if key in exempt:
            seen.add(key)
            R.ok(f"{path} added in {commit[:12]}: exempt, sealed before the gate ({exempt[key]})")
        else:
            gate_one(commit, path, piece, R)
    for key, why in sorted(exempt.items()):
        if key[0] == repo and key not in seen:
            R.note(f"exempt seal not in this history (another branch?): {key[2]} {key[1][:12]}")
    return R.finish("purpose gate")


# ---------------------------------------------------------------- seal integrity of a piece

def first_line_sha(text, pattern):
    m = re.search(pattern, text)
    return m.group(1) if m else None


def find_seal_commit(p, kind, R):
    """Return (commit, recorded THESIS md5 or None), or (None, None) after a FAIL."""
    d, cfg = p["dir"], p["seal"]
    given = cfg.get("commit")
    recorded_md5 = cfg.get("recorded_md5")
    found = None
    if kind == "manifest":
        man = rc.join(d, "SEAL_MANIFEST.md")
        adds = rc.out("log", "--diff-filter=A", "--format=%H", "HEAD", "--", man).split()
        if len(adds) != 1:
            R.fail(f"{man} added {len(adds)} times in HEAD's history; a seal is added once")
            return None, None
        found = adds[0]
        R.ok(f"seal commit {found[:12]}: the commit that added {man}")
        sealed = rc.blob("HEAD", rc.join(d, "SEALED"))
        if sealed is None:
            R.fail(f"{rc.join(d, 'SEALED')} is not present at HEAD")
        else:
            R.ok(f"{rc.join(d, 'SEALED')} present")
            named = first_line_sha(sealed.decode("utf-8", errors="replace"), rf"\bsealed at `?({SHA})`?")
            if named:
                full = rc.resolve(named)
                if full != found:
                    R.fail(f"SEALED names {named}, but {man} was added in {found[:12]}")
                else:
                    R.ok(f"SEALED names the same commit ({named})")
    elif kind == "record":
        rec_path = rc.join(d, "office", "SEAL.txt")
        rec = rc.blob("HEAD", rec_path)
        if rec is None:
            R.fail(f"{rec_path} is not present at HEAD")
            return None, None
        text = rec.decode("utf-8", errors="replace")
        named = first_line_sha(text, rf"Seal commit\s+({SHA})")
        if not named:
            R.fail(f"{rec_path} names no 'Seal commit <sha>'")
            return None, None
        found = rc.resolve(named)
        if not found:
            R.fail(f"{rec_path} names seal commit {named}, which is not in this repository")
            return None, None
        R.ok(f"seal commit {found[:12]}: named in {rec_path}")
        m = re.search(r"md5 of \S*THESIS\.md at the seal commit:\s*([0-9a-f]{32})", text)
        if m:
            recorded_md5 = recorded_md5 or m.group(1)
            if m.group(1) != recorded_md5:
                R.fail(f"{rec_path} gives THESIS md5 {m.group(1)}, the configuration {recorded_md5}")
    elif kind == "header":
        thesis = rc.blob("HEAD", rc.join(d, "THESIS.md"))
        head_text = thesis.decode("utf-8", errors="replace")[:3000] if thesis else ""
        named = first_line_sha(head_text, rf"at commit `({SHA})`")
        if named:
            R.note(f"THESIS.md header names commit {named}")
        if given:
            found = rc.resolve(given)
            if not found:
                R.fail(f"configured seal commit {given} is not in this repository")
                return None, None
            R.ok(f"seal commit {found[:12]}: given in the configuration ({p['seal'].get('why', 'no reason given')})")
        elif named:
            found = rc.resolve(named)
            R.ok(f"seal commit {found[:12]}: named in the THESIS.md header")
        else:
            R.fail("kind header: no seal commit in the configuration and none named in THESIS.md")
            return None, None
    else:
        R.fail(f"unknown seal kind {kind!r} (manifest, record or header)")
        return None, None
    if given and kind != "header" and rc.resolve(given) != found:
        R.fail(f"configured seal commit {given} differs from the one the piece records ({found[:12]})")
    return found, recorded_md5


def check_thesis(p, seal, recorded_md5, R):
    d, mode = p["dir"], p["seal"].get("thesis", "strict")
    path = rc.join(d, "THESIS.md")
    if not rc.is_ancestor(seal, "HEAD"):
        R.fail(f"seal commit {seal[:12]} is not an ancestor of HEAD")
    at_seal, at_head = rc.blob(seal, path), rc.blob("HEAD", path)
    if at_seal is None or at_head is None:
        R.fail(f"{path} missing at the seal commit or at HEAD")
        return None
    if recorded_md5:
        if rc.md5(at_seal) == recorded_md5:
            R.ok(f"{path} at the seal commit has the recorded md5 {recorded_md5}")
        else:
            R.fail(f"{path} at the seal commit is {rc.md5(at_seal)}, the record says {recorded_md5}")
    if at_head == at_seal:
        R.ok(f"{path} unchanged since the seal (md5 {rc.md5(at_head)})")
    elif mode == "append" and at_head.startswith(at_seal):
        R.ok(f"{path}: the sealed text is unchanged; {len(at_head) - len(at_seal)} bytes of amendments "
             f"appended below it (md5 at HEAD {rc.md5(at_head)})")
    elif mode == "append":
        R.fail(f"{path} changed above the sealed text since {seal[:12]} (only appended amendments are allowed)")
    else:
        R.fail(f"{path} changed since the seal: {rc.md5(at_seal)} at {seal[:12]}, {rc.md5(at_head)} at HEAD")
    return rc.md5(at_seal)


def check_manifest(p, seal, thesis_md5, R):
    d = p["dir"]
    man = rc.join(d, "SEAL_MANIFEST.md")
    at_seal, at_head = rc.blob(seal, man), rc.blob("HEAD", man)
    if at_head is None:
        R.fail(f"{man} is not present at HEAD")
        return
    if at_seal != at_head:
        R.fail(f"{man} changed since the seal commit")
    else:
        R.ok(f"{man} unchanged since the seal commit")
    listed = re.findall(r"^([0-9a-f]{32})  (\S.*?)\s*$", at_head.decode("utf-8", errors="replace"), re.M)
    if not listed:
        R.fail(f"{man} lists no md5 lines")
        return
    drift = {}
    for e in p["seal"].get("drift", []):
        if e["path"] == "THESIS.md":
            R.fail("THESIS.md is declared as drift; THESIS.md can never change after the seal")
            continue
        if not e.get("why"):
            R.fail(f"drift entry {e['path']} gives no reason")
        drift[e["path"]] = e
    names = {f for _, f in listed}
    addendum_path = rc.join(d, "THESIS_ADDENDUM.md")
    addendum = (rc.blob("HEAD", addendum_path) or b"").decode("utf-8", errors="replace")
    match = changed = 0
    for h, f in listed:
        cur = rc.blob("HEAD", rc.join(d, f))
        if f == "THESIS.md" and thesis_md5 and h != thesis_md5:
            R.fail(f"{man} gives THESIS.md {h}, but THESIS.md at the seal commit is {thesis_md5}")
        if cur is not None and rc.md5(cur) == h:
            match += 1
            if f in drift:
                R.fail(f"{f} is declared as drift but matches the seal; remove the stale declaration")
            continue
        e = drift.get(f)
        now = "missing" if cur is None else rc.md5(cur)
        if e and e.get("sealed_md5") == h and cur is not None and now in addendum:
            changed += 1
            R.ok(f"CHANGED AFTER SEAL, declared, HEAD md5 recorded in {addendum_path}: "
                 f"{f} sealed {h}, HEAD {now} ({e['why']})")
        elif e and e.get("sealed_md5") == h:
            R.fail(f"{f} changed after the seal and is declared, but its md5 at HEAD ({now}) is not "
                   f"recorded in {addendum_path}: a change after the seal is reported there, dated")
        elif e:
            R.fail(f"{f}: declared sealed_md5 {e.get('sealed_md5')} is not the manifest's {h}")
        else:
            R.fail(f"{f}: sealed {h}, HEAD {now}, and not declared")
    for f in sorted(set(drift) - names):
        R.fail(f"drift entry {f} is not in {man}")
    R.note(f"{len(listed)} sealed files: {match} match HEAD, {changed} changed after the seal and declared")


def piece(name, config):
    cfg = rc.load(config)
    p = cfg["pieces"].get(name)
    if p is None or "seal" not in p:
        raise SystemExit(f"config: no [pieces.{name}.seal]")
    R = rc.Report()
    rc.require_full_history()
    kind = p["seal"].get("kind")
    R.section(f"seal integrity: {name} ({p['dir']}/, kind {kind}, THESIS {p['seal'].get('thesis', 'strict')})")
    seal, recorded = find_seal_commit(p, kind, R)
    if seal:
        thesis_md5 = check_thesis(p, seal, recorded, R)
        if kind == "manifest":
            check_manifest(p, seal, thesis_md5, R)
    return R.finish(f"seal {name}")


def main(argv):
    config = argv[argv.index("--config") + 1] if "--config" in argv else rc.CONFIG
    if len(argv) >= 3 and argv[1] == "piece":
        return piece(argv[2], config)
    if len(argv) >= 2 and argv[1] == "purpose":
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exempt = argv[argv.index("--exempt") + 1] if "--exempt" in argv else os.path.join(here, "EXEMPT_SEALS.txt")
        repo = argv[argv.index("--repo") + 1] if "--repo" in argv else \
            os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]
        if not repo:
            raise SystemExit("purpose: pass --repo NAME (or run where GITHUB_REPOSITORY is set)")
        return purpose(exempt, repo)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
