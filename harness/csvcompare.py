#!/usr/bin/env python3
"""Compare the results tables an engine run wrote with the authors' published CSV files.

  csvcompare.py WORKDIR        # WORKDIR = the `work` directory of a harness/run.py run

The expected files are listed in tests/esttab_expected.json (Dataverse file id,
sha256, the path the do-file writes). They are fetched through cases.fetch()
into the cache and checked against the pinned hash. For each expected file the
run wrote, prints IDENTICAL or the first differing line pair. Exit 1 on any
difference.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cases as C  # noqa: E402

EXPECTED = os.path.join(ROOT, "tests", "esttab_expected.json")


def expected_files():
    return json.load(open(EXPECTED))["files"]


def compare_bytes(want, got):
    """None when identical, else (line number, expected line, our line)."""
    if want == got:
        return None
    a, b = want.split(b"\n"), got.split(b"\n")
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else b"<missing>"
        y = b[i] if i < len(b) else b"<missing>"
        if x != y:
            return i + 1, x.decode("utf-8", "replace"), y.decode("utf-8", "replace")
    return 0, "", ""


def main(work):
    bad = 0
    seen = 0
    for ent in expected_files():
        hits = glob.glob(os.path.join(work, "*", ent["target"]))
        if not hits:
            continue
        want = open(C.fetch(ent), "rb").read()
        for h in hits:
            seen += 1
            d = compare_bytes(want, open(h, "rb").read())
            if d is None:
                print(f"IDENTICAL  {ent['target']}  ({os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(h))))})")
            else:
                bad += 1
                print(f"DIFFERS    {ent['target']} line {d[0]}\n  authors: {d[1]}\n  ours:    {d[2]}")
    print(f"{seen} files compared, {bad} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
