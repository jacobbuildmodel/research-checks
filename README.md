# research-checks

Shared checks for the research repositories behind
[jacobbuildmodel.github.io](https://jacobbuildmodel.github.io): every prediction
there is sealed (its THESIS.md and scripts fixed by md5) before the data is
opened, then scored in public. These checks run on every commit, on GitHub's
free runners, so any reader can see from the Actions tab whether a seal still
holds and whether the published outputs still reproduce.

No AI runs inside these checks, and they use no secrets. Every action is
pinned by its full commit sha; every job runs on `ubuntu-26.04` with
`contents: read` only.

## The tiers

| Workflow | Tier | What fails it |
|---|---|---|
| `seal.yml` | (i) seal integrity | THESIS.md changed since its seal commit; a SEAL_MANIFEST md5 that no longer matches HEAD and is not declared and reported (below); SEALED or the seal record missing |
| `seal.yml` | (i) purpose gate | a commit that adds a seal marker without a valid purpose review (below) |
| `fast.yml` | (ii) fast | the piece's synthetic test suite, or its `NN_manifest.py --check` (every committed md5 and number, nothing rebuilt) |
| `standards.yml` | (iii) standards | the fast half of hdb-affordability's `check.sh` (STANDARDS v2: ASCII, advice words, headline and length, chart dark mode and 390px text, pinned and complete requirements, raw-file provenance), per piece |
| `rebuild.yml` | rebuild | deletes a piece's outputs, reruns its pipeline and compares every committed file; reports only unless called with `blocking: true` |

The tools are plain Python 3.11+ standard library, in `tools/`. They read
committed blobs (`git cat-file`), never the working copy.

### Seal integrity, in detail

A piece records its seal in one of three ways, set by `kind`:

- `manifest`: `<piece>/SEAL_MANIFEST.md` lists the md5 of every file the seal
  fixes, added in its own commit (the seal commit); `<piece>/SEALED` is added
  when the data is opened.
- `record`: `<piece>/office/SEAL.txt` names the seal commit and the THESIS md5.
- `header`: THESIS.md's header names the commit, or the configuration gives it
  (`commit`, with `why`, and optionally the `recorded_md5` the piece's own
  records give for THESIS.md at that commit).

THESIS.md must be byte-identical to the one at the seal commit. A piece whose
own rules allow appended, dated AMENDMENT blocks can set `thesis = "append"`:
then the sealed text must be an exact prefix of THESIS.md at HEAD.

For `manifest` pieces every listed md5 must match HEAD. A file changed after
the seal passes only if both hold:

1. the caller's configuration declares it in `drift`, with the md5 the
   manifest gives it and a reason; and
2. the piece's THESIS_ADDENDUM.md records the file's md5 at HEAD (the pieces'
   own rule: a change after the seal is reported there, dated).

So a further change to a declared file fails until the addendum reports it,
and THESIS.md can never be declared.

### The purpose gate

From `office/PURPOSE_PRINCIPLES.md` (15 October 2026): no seal without a GO or
PAPER TRACK purpose review. Every commit in HEAD's history that **adds**
`<piece>/SEALED`, `<piece>/SEAL_MANIFEST*` or `<piece>/office/SEAL.txt`
(renaming another file into place counts as adding it) fails
unless, in that same commit:

- `<piece>/PURPOSE_REVIEW.md` exists;
- its header passes the purpose-review header rules (`tools/purpose_header.py`,
  ported unchanged from the moderator's `purpose_gate.py`);
- its verdict is `GO` or `PAPER TRACK`;
- its `reviewed_md5` is the md5 of `<piece>/THESIS.md` as committed there.

The gate needs no configuration, so a new piece is covered before anyone adds
it to a config file.

### Seals exempt from the purpose gate

Seals made before the gate existed. The list is closed: a seal made after the
gate meets the gate and is never added here. The machine-read copy is
`EXEMPT_SEALS.txt`.

| Repository | Piece | Commit | Path | Sealed |
|---|---|---|---|---|
| coe-analysis | erp | `becba02` | `erp/office/SEAL.txt` | 26 Sep 2026 (seal commit `6d2a345`) |
| coe-analysis | pwm | `e5f877b` | `pwm/SEAL_MANIFEST.md` | 28 Sep 2026 |
| coe-analysis | pwm | `dafb176` | `pwm/SEALED` | data opened 28 Sep 2026 |
| coe-analysis | sgd | `9e46034` | `sgd/SEAL_MANIFEST.md` | 3 Oct 2026 |
| coe-analysis | sgd | `59789e4` | `sgd/SEALED` | data opened 3 Oct 2026 |
| hdb-affordability | cargradient | `7ee9b91` | `cargradient/SEAL_MANIFEST.md` | 12 Oct 2026 (branch cargradient-wip) |
| hdb-affordability | cargradient | `800ac1f` | `cargradient/SEALED` | 12 Oct 2026 (branch cargradient-wip) |

The older seals of hdb-affordability (affordability, financing) and
gst-passthrough added none of these markers, so the gate has nothing to exempt
there; their seals are still checked by tier (i).

## Using it from a research repository

1. Describe the pieces in `.github/research-checks.toml`. A piece takes part
   in a tier when it has that tier's table:

   ```toml
   [pieces.pwm]
   dir = "pwm"                          # "." for a piece at the repository root
   python = "3.11"                      # default 3.11
   requirements = "pwm/requirements.txt"  # space-separated if several

   [pieces.pwm.seal]
   kind = "manifest"                    # manifest | record | header
   thesis = "strict"                    # strict | append
   drift = [
     { path = "12_figures.py", sealed_md5 = "d5112e9748ef097b9f33e56958dd86b4", why = "charts; THESIS_ADDENDUM items 2, 3, 7, 9, 10" },
   ]

   [pieces.pwm.fast]
   tests = "pwm/tests"                  # unittest discovery, test_*.py
   manifest = "python3 pwm/14_manifest.py --check"

   [pieces.pwm.standards]
   length_exempt = []                   # article paths relative to the piece
   warn = { length = "why this is reported, not blocking" }
   skip = { provenance = "why this check does not apply" }
   exclude = { "fonts/" = "vendored files" }
   parity = "./check.sh"                # optional: diff the original against the port

   [pieces.pwm.rebuild]
   clean = "pwm/out pwm/figs"
   command = "bash pwm/run_all.sh"
   ```

   Every `warn`, `skip`, `exclude` and `drift` entry carries its reason and is
   printed on every run; nothing passes silently.

2. Call the workflows, each pinned by the same full sha twice (a reusable
   workflow cannot read its own ref, so the tools are checked out at
   `checks_sha`):

   ```yaml
   permissions:
     contents: read
   jobs:
     seal:
       uses: jacobbuildmodel/research-checks/.github/workflows/seal.yml@<sha>
       with:
         checks_sha: <sha>
     fast:
       uses: jacobbuildmodel/research-checks/.github/workflows/fast.yml@<sha>
       with:
         checks_sha: <sha>
   ```

Results appear as one job per piece in the caller's Actions tab, each with
its full output in the job summary.

## Testing this repository

`selftest.yml` runs on every pull request: the unit tests in `tests/` (each
builds a throwaway git repository and runs a tool in it), actionlint over
every workflow, and every reusable workflow called end to end on the fixture
piece in `tests/e2e/piece/` (a valid seal with a valid purpose review). The
fixture is not research.

```bash
python3 -m unittest discover -s tests -v
```

Licence: MIT (see LICENSE).
