"""esttab to CSV: layout on a synthetic panel, the star rule, refusals, and the authors' files.

The comparison with the authors' CSV files (HNPXO1 tables 2 and 9, byte for
byte) runs the open cases through the harness and needs the case files in the
cache; it skips when they are not there. Nothing here fetches from the network.
"""
import io
import json
import os
import sys

import numpy as np
import pytest
from scipy import stats as SS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "harness"))

from ose import commands  # noqa: E402,F401
from ose.commands import esttab as E  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402
from ose.interp import Interp  # noqa: E402

from test_reghdfe import panel  # noqa: E402

CALL = ('esttab m1 m2 using "out.csv", replace mtitle(m1 m2) se b(%12.4f) '
        'star(* 0.1 ** 0.05 *** 0.01) s(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps')
SETUP = ("use p, clear\n"
         "reghdfe y i.zone##i.after if y < 100, absorb(firm ind_year) cluster(firm)\nest store m1\n"
         "reghdfe y c.x1##i.after i.g, absorb(firm ind_year) cluster(firm)\nest store m2\n")


def write_p(tmp_path):
    d = panel()
    d["after"] = (d["year"] >= 4).astype(float)
    d["zone"] = (d["firm"] % 2).astype(float)       # constant within firm: absorbed, so omitted
    vs = [Variable(k, "double", d[k].astype(float)) for k in ("y", "x1", "g", "firm", "year", "ind_year", "after", "zone")]
    write_dta(Dataset(vs), str(tmp_path / "p.dta"))


def run(src, tmp_path):
    p = tmp_path / "t.do"
    p.write_text(src)
    out = io.StringIO()
    it = Interp(cwd=str(tmp_path), out=out)
    it.run_file(str(p))
    return it, out.getvalue()


def table(tmp_path, call=CALL):
    write_p(tmp_path)
    it, out = run(SETUP + call + "\n", tmp_path)
    raw = (tmp_path / "out.csv").read_bytes().decode()
    return it, out, raw, None


def cells(line):
    assert line.startswith('="') and line.endswith('"')
    return line[2:-1].split('",="')


def test_layout_and_message(tmp_path):
    it, out, raw, _ = table(tmp_path)
    assert "(output written to out.csv)" in out.splitlines()
    assert raw.endswith('"\n') and "\r" not in raw
    rows = [cells(l) for l in raw.split("\n")[:-1]]
    assert rows[0] == ["", "(1)", "(2)"]
    assert rows[1] == ["", "m1", "m2"]
    names = [r[0] for r in rows[2:-4]]
    # every model's names in its own order, new names appended, base levels shown, _cons last
    assert names[:8] == ["0.zone", "", "1.zone", "", "0.after", "", "1.after", ""]
    stems = [n for n in names if n]
    assert stems == ["0.zone", "1.zone", "0.after", "1.after", "0.zone#0.after", "0.zone#1.after", "1.zone#0.after",
                     "1.zone#1.after", "x1", "0.after#c.x1", "1.after#c.x1", "1.g", "2.g", "3.g", "_cons"]
    assert rows[-4][0] == "N" and rows[-3][0] == "r2_a"
    assert rows[-4][1] == f"{it.estimates['m1']['N']:.0f}" and rows[-4][2] == f"{it.estimates['m2']['N']:.0f}"
    assert rows[-3][1] == f"{it.estimates['m1']['r2_a']:.4f}"
    assert rows[-2] == ["Standard errors in parentheses"]
    assert rows[-1] == ["* p<0.1, ** p<0.05, *** p<0.01"]
    assert all(len(r) == 3 for r in rows[:-2])


def test_cells_follow_the_estimates(tmp_path):
    it, _, raw, _ = table(tmp_path)
    rows = [cells(l) for l in raw.split("\n")[:-1]]
    body = {rows[i][0]: (rows[i], rows[i + 1]) for i in range(2, len(rows) - 4, 2)}
    for k, key in enumerate(("m1", "m2"), start=1):
        e = it.estimates[key]
        for j, n in enumerate(e["_colnames"]):
            b, se = float(e["_b"][j]), float(np.sqrt(e["V"][j, j]))
            bc, sc = body[n][0][k], body[n][1][k]
            if se == 0:                               # omitted by the fixed effects
                assert (bc, sc) == ("0.0000", "(.)")
                continue
            p = 2 * SS.t.sf(abs(b / se), e["df_r"])
            stars = "***" if p < .01 else "**" if p < .05 else "*" if p < .1 else ""
            assert bc == f"{b:.4f}{stars}" and sc == f"({se:.4f})"
    # a base level and an omitted column look the same; a name the model lacks is empty
    assert body["0.zone"][0][1:] == ["0.0000", ""] and body["0.zone"][1][1:] == ["(.)", ""]
    assert body["x1"][0][1] == "" and body["1.g"][1][1] == ""
    assert body["1.zone"][0][1] == "0.0000" and body["1.zone"][1][1] == "(.)"   # zone is absorbed


def test_star_cutpoints():
    df = 40
    for cut, mark in ((0.01, "***"), (0.05, "**"), (0.1, "*")):
        t = SS.t.isf(cut / 2, df)
        assert E._star(t * 1.001, 1.0, df) == mark
        assert E._star(-t * 1.001, 1.0, df) == mark
        below = {"***": "**", "**": "*", "*": ""}[mark]
        assert E._star(t * 0.999, 1.0, df) == below
    # each model's own df_r: the same t is significant with many clusters, not with few
    assert E._star(2.2, 1.0, 1000) == "**" and E._star(2.2, 1.0, 3) == ""


@pytest.mark.parametrize("call, what", [
    ('esttab m1 m2 using "out.csv", replace mtitle(m1 m2) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps label', "esttab option label"),
    ('esttab m1 m2 using "out.csv", replace mtitle(m1 m2) b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "without se"),
    ('esttab m1 m2 using "out.csv", replace mtitle(m1 m2) se b(%12.3f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "b(%12.3f)"),
    ('esttab m1 m2 using "out.csv", replace mtitle(m1 m2) se b(%12.4f) star(* 0.1 ** 0.05) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "star("),
    ('esttab m1 m2 using "out.csv", replace mtitle(m1 m2) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2, fmt(%9.0f %9.4f)) compress nogaps', "esttab s("),
    ('esttab m1 m2 using "out.txt", replace mtitle(m1 m2) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "only .csv"),
    ('esttab m1 m3 using "out.csv", replace mtitle(m1 m3) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "no stored estimate"),
    ('esttab m1 m2 using "out.csv", replace mtitle(m1) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "mtitle()"),
    ('esttab m1 m2, replace mtitle(m1 m2) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "without using"),
    ('esttab m1 m2 using "nodir/out.csv", replace mtitle(m1 m2) se b(%12.4f) star(* 0.1 ** 0.05 *** 0.01) '
     's(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps', "directory missing"),
])
def test_everything_else_is_unsupported(tmp_path, call, what):
    write_p(tmp_path)
    with pytest.raises(Exception) as ei:
        run(SETUP + call + "\n", tmp_path)
    assert "not implemented" in str(ei.value) and what in str(ei.value)
    assert not (tmp_path / "out.csv").exists()


def test_row_union_puts_new_names_before_constant():
    a = {"_fullnames": ["x", "z", "_cons"]}
    b = {"_fullnames": ["y", "x", "w", "_cons"]}
    assert E._rows(None, [a, b]) == ["x", "z", "y", "w", "_cons"]


# --- the authors' own files -------------------------------------------------

CASES = os.path.join(ROOT, "tests", "cases", "open")
CACHE = os.environ.get("OSE_CACHE", os.path.expanduser("~/.cache/open-stats-engine"))


def _cached(entry):
    p = os.path.join(CACHE, "dataverse", f"{entry['file_id']}{'.orig' if entry.get('original') else ''}")
    return os.path.exists(p)


@pytest.mark.parametrize("case_id, target", [
    ("dv-HNPXO1-02_table2_baseline", "output/tables/table2_baseline.csv"),
    ("dv-HNPXO1-09_table9_ddd", "output/tables/table9_ddd.csv"),
])
def test_authors_csv_byte_for_byte(tmp_path, case_id, target):
    import cases as C
    import csvcompare as CC
    import run as R
    case = C.load(os.path.join(CASES, case_id + ".json"))
    want = [e for e in CC.expected_files() if e["target"] == target][0]
    needed = case["files"] + [case["expected_log"], want]
    if not all(_cached(e) for e in needed):
        pytest.skip("case files not in the cache (no network in unit tests)")
    res = R.run_case(case, str(tmp_path))
    # Every command's output matches; rules .13 credit only echoes they can read (a `///` regression is counted as
    # AMBIGUOUS), so the check is that no row is anything else.
    s = res["summary"]
    assert s["cls_MATCH"] + s["cls_AMBIGUOUS"] == s["commands"] and s["cls_MATCH"] > 0
    ours = (tmp_path / case_id / target).read_bytes()
    theirs = open(C.fetch(want), "rb").read()
    assert CC.compare_bytes(theirs, ours) is None


def test_compare_bytes_reports_first_difference():
    import csvcompare as CC
    assert CC.compare_bytes(b"a\nb\n", b"a\nb\n") is None
    assert CC.compare_bytes(b"a\nb\nc\n", b"a\nX\nc\n") == (2, "b", "X")
    assert CC.compare_bytes(b"a\nb\n", b"a\n") == (2, "b", "")


def test_expected_list_is_pinned():
    files = json.load(open(os.path.join(ROOT, "tests", "esttab_expected.json")))["files"]
    assert len(files) == 12 and all(len(f["sha256"]) == 64 and f["file_id"] for f in files)
