"""Matching rules 8.2: what the open harness checks on the wording table, entry by entry.

Each entry needs a sample line below, written by us (no line here is copied from a log). A table entry without a
sample fails, so the check covers every entry of whichever table is installed. Two checks run on each sample:

1. the sample matches, is rewritten, and keeps its sequence of numeric tokens;
2. the same, with a digit inserted at every position of the sample: wherever the entry still matches, the rewrite
   keeps the numeric tokens of that variant.

An entry listed in TEXT_ONLY rewrites a line that never holds a number (its pattern is anchored at both ends with no
room for one); its sample has no numbers, and check 2 is what covers it. These are checks on samples, not a proof
over all lines."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "harness"))

import logmatch as L  # noqa: E402

SAMPLES = {
    "merge-result-header": "    Result                      # of obs.",
    "merge-not-matched": "    not matched                         1,204",
    "merge-matched": "    matched                            38,417  (_merge==3)",
    "append-note-prefix": "(note: variable q12 was str9, now str24 to accommodate using data's values)",
    "coef-table-titles-t": "         y1 |      Coef.   Std. Err.      t    P>|t|     [95% Conf. Interval]",
}
TEXT_ONLY = {"merge-result-header"}
NUMTOK = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?(?:e[-+]\d+)?")


def numbers(line):
    return [t for t in NUMTOK.findall(line) if any(c.isdigit() for c in t)]


def test_every_entry_has_a_sample_and_keeps_its_numbers():
    assert L.WORDING, "wording table is empty"
    for eid, rx, rep in L.WORDING:
        literal = re.sub(r"\\\d", "", rx.pattern + rep)  # group references such as \1 are not literal digits
        assert not any(c.isdigit() for c in literal), f"{eid}: digit in regex or replacement"
        assert eid in SAMPLES, f"{eid}: no sample line in tests/unit/test_wording_table.py"
        line = SAMPLES[eid]
        assert rx.search(line), f"{eid}: sample does not match"
        out = rx.sub(rep, line)
        assert out != line, f"{eid}: sample not rewritten"
        assert numbers(out) == numbers(line), f"{eid}: numeric tokens changed: {line!r} -> {out!r}"
        assert bool(numbers(line)) != (eid in TEXT_ONLY), f"{eid}: a sample needs numbers unless the entry is TEXT_ONLY"


def test_a_digit_anywhere_in_a_sample_survives_the_rewrite():
    for eid, rx, rep in L.WORDING:
        line, matched = SAMPLES[eid], 0
        for i in range(len(line) + 1):
            variant = line[:i] + "7" + line[i:]
            if rx.search(variant):
                matched += 1
                assert numbers(rx.sub(rep, variant)) == numbers(variant), f"{eid}: digit at {i} changed"
        if eid in TEXT_ONLY:
            assert matched == 0, f"{eid}: TEXT_ONLY entry matched a line holding a digit"


def test_rewrite_reaches_the_new_wording():
    assert L.reword("    not matched                         1,204") == "    Not matched                         1,204"
    assert L.reword("    Result                      # of obs.") == "    Result Number of obs"
