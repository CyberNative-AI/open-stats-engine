"""Write the two reader example files, byte-for-byte reproducible.

usage: python3 -I make_inputs.py <engine-dir> <output-dir>

Uses the engine's own .dta writer with the header timestamp pinned, so the
same revision always produces the same bytes. The IDs below are the single
source of truth for the expected counts (see expected.json).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

engine, out = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(engine))
sys.dont_write_bytecode = True
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402

# Master (roster.dta) is deliberately not in key order.
ROSTER = [(103, "Cy"), (101, "Ada"), (107, "Eli"), (102, "Bo"), (105, "Fay"), (104, "Dev"), (106, "Gus")]
# Using (scores.dta) is also unsorted; 203 and 204 appear only here.
SCORES = [(204, 83), (104, 88), (106, 64), (203, 90), (105, 77), (107, 59)]


def column(name, kind, values, label):
    data = np.array(values, dtype=object if kind.startswith("str") else float)
    return Variable(name, kind, data, label=label)


real_strftime = time.strftime
time.strftime = lambda fmt, *a: "17 Jul 2031 13:57"
out.mkdir(parents=True, exist_ok=True)
write_dta(Dataset([
    column("id", "int", [r[0] for r in ROSTER], "Person ID"),
    column("name", "str3", [r[1] for r in ROSTER], "First name"),
]), out / "roster.dta")
write_dta(Dataset([
    column("id", "int", [r[0] for r in SCORES], "Person ID"),
    column("score", "byte", [r[1] for r in SCORES], "Score"),
]), out / "scores.dta")
time.strftime = real_strftime

master = {r[0] for r in ROSTER}
using = {r[0] for r in SCORES}
assert len(master) == len(ROSTER) and len(using) == len(SCORES)
expected = {
    "master_rows": len(ROSTER),
    "using_rows": len(SCORES),
    "matched_ids": sorted(master & using),
    "master_only_ids": sorted(master - using),
    "using_only_ids": sorted(using - master),
}
expected |= {
    "matched": len(expected["matched_ids"]),
    "from_master": len(expected["master_only_ids"]),
    "from_using": len(expected["using_only_ids"]),
}
expected["not_matched"] = expected["from_master"] + expected["from_using"]
expected["rows_after_merge"] = expected["matched"] + expected["not_matched"]
(out / "expected.json").write_text(json.dumps(expected, indent=2) + "\n")
print(json.dumps(expected, indent=2))
