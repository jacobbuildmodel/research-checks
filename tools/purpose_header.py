"""Header rules of a purpose review, ported from the WEBSITE moderator's
checker_tools/purpose_gate.py (validate() and header(), 15 Oct 2026). Only the
header check is ported: the portfolio status report stays with the moderator.

A review is a Markdown file whose first lines are a header block:

    ---
    piece: pwm
    reviewed_md5: <32 hex: md5 of the THESIS.md under review>
    verdict: GO
    ...
    ---

validate(text, thesis_md5) returns (fields, errors). The rules are the
moderator's, unchanged; the one difference is that the md5 to compare with is
passed in (the seal check computes it from the committed THESIS.md blob)
rather than read from a file path.

Usage:  python3 purpose_header.py <review.md> [--md5-of <THESIS.md>]
"""
import hashlib
import re
import sys

GATES = ("G0", "G1", "G2", "G3", "G4", "G5")  # G0 added in PURPOSE_PRINCIPLES v1
GRADES = {"PASS", "WEAK", "FAIL"}
VERDICTS = {"GO", "PAPER TRACK", "REDESIGN", "STOP"}
STAGES_REVIEW = {"cp0", "seal", "reader-fail", "post-result", "portfolio"}
REQUIRED = ("piece", "repo", "ref", "reviewed", "reviewed_md5", "stage", "date", "reviewer",
            *GATES, "headline_yes", "headline_no", "verdict")
# Before results exist (cp0, seal) v1 also needs the numbers that make G3 and G5 checkable.
FORWARD = ("p_zero_cell", "smallest_effect", "positive_control", "kill_criteria", "decision_date")
FORWARD_STAGES = {"cp0", "seal"}
# The verdicts that let a seal go ahead (the seal gate in research-checks).
SEAL_VERDICTS = {"GO", "PAPER TRACK"}


def header(text):
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None, ["no header block at the top"]
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, ["header block not closed with ---"]
    fields = {}
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        if ":" not in line:
            return None, [f"bad header line: {line!r}"]
        k, v = line.split(":", 1)
        fields[k.strip()] = v.strip()
    return fields, []


def validate(text, thesis_md5=None):
    h, errs = header(text)
    if h is None:
        return None, errs
    # Reviews are immutable records. A review without "principles: v1" was made under v0.1 (gates
    # G1-G5, no G0, no forward numbers) and is checked by the v0.1 rules.
    v1 = h.get("principles") == "v1"
    gates = GATES if v1 else GATES[1:]
    for k in REQUIRED:
        if k == "G0" and not v1:
            continue
        if not h.get(k):
            errs.append(f"missing {k}")
    if v1 and h.get("stage") in FORWARD_STAGES:
        for k in FORWARD:
            if not h.get(k):
                errs.append(f"missing {k} (required before results, PURPOSE_PRINCIPLES v1 G3/G5)")
    if errs:
        return h, errs
    if not re.fullmatch(r"[0-9a-f]{32}", h["reviewed_md5"]):
        errs.append("reviewed_md5 is not 32 hex characters")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", h["date"]):
        errs.append("date is not YYYY-MM-DD")
    if h["stage"] not in STAGES_REVIEW:
        errs.append(f"stage {h['stage']!r} not in {sorted(STAGES_REVIEW)}")
    for g in gates:
        if h[g] not in GRADES:
            errs.append(f"{g} {h[g]!r} not PASS/WEAK/FAIL")
    if h["verdict"] not in VERDICTS:
        errs.append(f"verdict {h['verdict']!r} not in {sorted(VERDICTS)}")
    if errs:
        return h, errs
    grades = [h[g] for g in gates]
    # Consistency rules (PURPOSE_PRINCIPLES sections 2 and 5).
    if h["verdict"] == "GO" and "FAIL" in grades:
        errs.append("GO with a failed gate: a reader article must pass every gate")
    if h["verdict"] == "GO" and h["G3"] != "PASS":
        errs.append("GO needs G3 PASS: both results must be news")
    if h["G1"] == "FAIL" and h["G4"] == "FAIL" and h["verdict"] != "STOP":
        errs.append("G1 and G4 both FAIL (no decision, nobody served): verdict must be STOP")
    if v1 and h["stage"] in FORWARD_STAGES:
        try:
            pz = float(h["p_zero_cell"])
        except ValueError:
            pz = None
            errs.append("p_zero_cell is not a number between 0 and 1")
        if pz is not None and not 0 <= pz <= 1:
            errs.append("p_zero_cell is not between 0 and 1")
        elif pz is not None and pz > 0.5 and h["verdict"] == "GO":
            errs.append("GO with more than half the probability in the zero cell (G3)")
    if (h.get("G0") == "FAIL" or h["G1"] == "FAIL") and h["verdict"] == "GO":
        errs.append("GO with G0 or G1 failed")
    if h["headline_yes"].strip().lower() == h["headline_no"].strip().lower():
        errs.append("headline_yes and headline_no are the same: write one per result")
    if thesis_md5 is not None and thesis_md5 != h["reviewed_md5"]:
        errs.append(f"reviewed_md5 {h['reviewed_md5']} != md5 of the THESIS.md being sealed {thesis_md5}")
    return h, errs


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    md5 = None
    if "--md5-of" in argv:
        md5 = hashlib.md5(open(argv[argv.index("--md5-of") + 1], "rb").read()).hexdigest()
    h, errs = validate(open(argv[1], encoding="utf-8").read(), md5)
    if errs:
        print("INVALID: " + "; ".join(errs))
        return 1
    print(f"VALID ({h.get('principles', 'v0.1')}): {h['piece']} {h['stage']} {h['date']} "
          f"verdict={h['verdict']} " + " ".join(f"{g}={h[g]}" for g in GATES if g in h))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
