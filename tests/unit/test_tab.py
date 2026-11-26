"""tabulate on synthetic data. Every expected table below was written by hand from the column widths stated beside
it, not produced by running the engine and not copied from any log. The comparisons against authors' published logs run
in the open harness, which fetches the logs at test time."""
import io
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from ose import commands  # noqa: E402,F401
from ose import missing as M  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.errors import StataError, Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402


def mk(cols, labels=None):
    """cols: list of (name, values, variable label, value-label name). Returns (interp, output buffer)."""
    vs = [Variable(n, "double", np.asarray(v, dtype=np.float64), label=lab, vlabel=vl) for n, v, lab, vl in cols]
    out = io.StringIO()
    it = Interp(out=out)
    it.ds = Dataset(vs, value_labels=labels or {})
    return it, out


def rep(values, counts):
    return np.repeat(np.array(values, dtype=np.float64), counts)


def rows_of(text):
    """First cell of each table row (the part before the bar), skipping header and rules."""
    return [l.split("|")[0].strip() for l in text.split("\n") if "|" in l and "Freq." not in l]


# One-way: a blank line, the header, a rule, one row per value, a rule, Total. The stub is 11 wide, the frequency
# column 11, percent and cumulative 12 each; Total has no cumulative cell. A direct dispatch ends at the Total row.
GROUP = """
      Group |      Freq.     Percent        Cum.
------------+-----------------------------------
          1 |          2       20.00       20.00
          2 |          3       30.00       50.00
          3 |          5       50.00      100.00
------------+-----------------------------------
      Total |         10      100.00
"""

SIZE = """
  Firm size |      Freq.     Percent        Cum.
------------+-----------------------------------
      Small |      1,500       75.00       75.00
      Large |        500       25.00      100.00
------------+-----------------------------------
      Total |      2,000      100.00
"""


def test_one_way_numeric_with_label_and_stored_results():
    it, out = mk([("grp", rep([1, 2, 3], [2, 3, 5]), "Group", "")])
    it.dispatch("tab grp")
    assert out.getvalue() == GROUP
    assert it.r == {"N": 10.0, "r": 3.0}


def test_one_way_value_labels_and_thousands_separator():
    it, out = mk([("size", rep([1, 2], [1500, 500]), "Firm size", "sz")], {"sz": {1: "Small", 2: "Large"}})
    it.dispatch("tab size")
    assert out.getvalue() == SIZE


def test_one_way_generate_makes_dummies():
    it, out = mk([("grp", rep([1, 2, 3], [2, 3, 5]), "Group", "")])
    it.dispatch("tab grp, gen(g)")
    assert out.getvalue() == GROUP
    assert [int(it.ds.find(f"g{k}").data.sum()) for k in (1, 2, 3)] == [2, 3, 5]
    assert it.ds.find("g1").type == "byte" and not it.ds.has("g4")


def test_nolabel_shows_codes():
    it, out = mk([("size", rep([1, 2], [3, 1]), "Owner", "own")], {"own": {1: "Private", 2: "Public"}})
    it.dispatch("tab size, nolabel")
    lines = out.getvalue().split("\n")
    assert lines[1] == "      Owner |      Freq.     Percent        Cum."
    assert lines[3] == "          1 |          3       75.00       75.00"
    assert lines[4] == "          2 |          1       25.00      100.00"


def test_if_and_in_select_rows():
    it, out = mk([("g", [1, 1, 2, 2, 2, 3], "g", ""), ("x", [0, 1, 0, 0, 0, 1], "x", "")])
    it.dispatch("tab g if x == 0")
    assert "Total |          4      100.00" in out.getvalue()
    assert it.r["N"] == 4 and it.r["r"] == 2
    it2, _ = mk([("g", [1, 1, 2, 2, 2, 3], "g", "")])
    it2.dispatch("tab g in 1/2")
    assert it2.r["N"] == 2 and it2.r["r"] == 1


def test_missing_excluded_by_default_included_with_option():
    it, out = mk([("v", [1, 1, 2, M.SYSMISS, M.EXT["a"]], "v", "")])
    it.dispatch("tab v")
    assert it.r["N"] == 3
    assert rows_of(out.getvalue()) == ["1", "2", "Total"]
    out.truncate(0)
    out.seek(0)
    it.dispatch("tab v, missing")
    assert it.r["N"] == 5 and it.r["r"] == 4
    assert rows_of(out.getvalue()) == ["1", "2", ".", ".a", "Total"]


def test_sort_descending_frequency_and_tie_refused():
    it, out = mk([("v", [1, 2, 2, 2, 3, 3], "v", "")])
    it.dispatch("tab v, sort")
    assert rows_of(out.getvalue()) == ["2", "3", "1", "Total"]
    it2, o2 = mk([("v", [1, 2, 2, 3, 3], "v", "")])
    with pytest.raises(Unsupported):
        it2.dispatch("tab v, sort")
    assert o2.getvalue() == ""


def test_generate_missing_rows_and_existing_name():
    it, out = mk([("v", [5, 7, M.SYSMISS, 7], "v", "")])
    it.dispatch("tab v, gen(d)")
    assert list(it.ds.find("d1").data[:2]) == [1.0, 0.0]
    assert it.ds.find("d1").data[2] == M.SYSMISS
    with pytest.raises(StataError) as e:
        it.dispatch("tab v, gen(d)")
    assert e.value.rc == 110


@pytest.mark.parametrize("cmd", [
    "tab a b, col", "tab a b, cell", "tab a b, row col", "tab a b, sort", "tab a b, gen(x)", "tab a b, exact",
    "tab a b, nofreq", "tab a b [fw=a]", "tab a, chi2", "tab a [fw=b]", "tab a, row", "tab a, matcell(m)", "tab1 a", "tab2 a b", "tabi 1 2",
    "tab a, exact", "tab a, nofreq", "tab s", "tab a, plot",
])
def test_unsupported_never_approximates(cmd):
    it, out = mk([("a", [1, 2], "a", ""), ("b", [1, 2], "b", "")])
    it.ds.add(Variable("s", "str3", np.array(["x", "y"], dtype=object)))
    with pytest.raises(Unsupported):
        it.dispatch(cmd)
    assert out.getvalue() == ""


def test_stub_width_rule_unseen_cases_refused():
    # a label table holding a text longer than every value shown: no log says which one sizes the stub
    it, _ = mk([("v", [1, 1], "v", "l")], {"l": {1: "a", 2: "a very long label for an absent value"}})
    with pytest.raises(Unsupported):
        it.dispatch("tab v")
    it, _ = mk([("v", [1.5, 2.5], "v", "")])
    with pytest.raises(Unsupported):
        it.dispatch("tab v")
    it, _ = mk([("v", [1, 2], "one two three four five six seven eight nine ten eleven twelve", "")])
    with pytest.raises(Unsupported):  # four or more header lines
        it.dispatch("tab v")
    it, _ = mk([("v", [1, 2], "ab abcdefghijklmnopqrstuvwxyz0123456789", "")])
    with pytest.raises(Unsupported):  # a long word after other words
        it.dispatch("tab v")


def test_east_asian_width_pads_by_display_columns():
    # a wide (East Asian) character takes two display columns, so it pads as two
    from ose.commands.tab import dispw, rjust
    assert rjust("東京", 10) == " " * 6 + "東京"
    assert rjust("大阪市", 10) == " " * 4 + "大阪市"
    assert dispw("abc") == 3 and dispw("東京") == 4


def test_errors():
    it, _ = mk([("a", [], "a", "")])
    with pytest.raises(StataError) as e:
        it.dispatch("tab a")
    assert e.value.rc == 2000
    with pytest.raises(StataError) as e:
        it.dispatch("tab")
    assert e.value.rc == 100
    with pytest.raises(StataError) as e:
        it.dispatch("tab a a a")
    assert e.value.rc == 103


def test_abbreviations_and_capture():
    it, out = mk([("v", [1, 2], "v", "")])
    for w in ("ta v", "tab v", "tabu v", "tabulate v"):
        it.dispatch(w)
    it.dispatch("quietly tab v")
    assert out.getvalue().count("Total") == 4
    with pytest.raises(Unsupported):  # capture never turns unsupported into a return code
        it.dispatch("capture tab v v, col")


# ---------------------------------------------------------------- two-way
# Cells are 10 wide, one space apart, with a space before the bar; the column variable's name is centred over the
# cell block; the Total column is 10 wide with a trailing space on data rows
# (written `~` below so an editor cannot strip it). A table without chi2 ends on a blank line.
AB = [(1, 0, 3), (1, 1, 1), (2, 0, 2), (2, 1, 4)]  # (a, bb, count)

TWO_AB = """
           |          bb
         a |         0          1 |     Total
-----------+----------------------+----------
         1 |         3          1 |         4~
         2 |         2          4 |         6~
-----------+----------------------+----------
     Total |         5          5 |        10~

""".replace("~\n", " \n")

TWO_AB_ROW = """
+----------------+
| Key            |
|----------------|
|   frequency    |
| row percentage |
+----------------+

           |          bb
         a |         0          1 |     Total
-----------+----------------------+----------
         1 |         3          1 |         4~
           |     75.00      25.00 |    100.00~
-----------+----------------------+----------
         2 |         2          4 |         6~
           |     33.33      66.67 |    100.00~
-----------+----------------------+----------
     Total |         5          5 |        10~
           |     50.00      50.00 |    100.00~

""".replace("~\n", " \n")


def ab():
    a = [r for r, _, n in AB for _ in range(n)]
    b = [c for _, c, n in AB for _ in range(n)]
    return mk([("a", a, "", ""), ("bb", b, "", "")])


def test_two_way_frequencies():
    it, out = ab()
    it.dispatch("tab a bb")
    assert out.getvalue() == TWO_AB
    assert it.r["N"] == 10 and it.r["r"] == 2 and it.r["c"] == 2


def test_two_way_row_percentages():
    it, out = ab()
    it.dispatch("tab a bb, row")
    assert out.getvalue() == TWO_AB_ROW


def test_two_way_chi2_agrees_with_scipy_and_is_stored():
    from scipy.stats import chi2_contingency
    tables = [
        [[3, 1], [2, 4]],
        [[10, 4, 6], [3, 9, 8]],
        [[12, 5], [7, 11], [4, 9]],
    ]
    for tab in tables:
        tab = np.array(tab)
        a = [i + 1 for i in range(tab.shape[0]) for j in range(tab.shape[1]) for _ in range(tab[i, j])]
        b = [j for i in range(tab.shape[0]) for j in range(tab.shape[1]) for _ in range(tab[i, j])]
        it, out = mk([("a", a, "", ""), ("b", b, "", "")])
        it.dispatch("tab a b, chi2")
        stat, p, df, _ = chi2_contingency(tab, correction=False)
        assert it.r["chi2"] == pytest.approx(stat, rel=1e-12)
        assert it.r["p"] == pytest.approx(p, rel=1e-12)
        assert it.r["N"] == tab.sum() and it.r["r"] == tab.shape[0] and it.r["c"] == tab.shape[1]
        line = out.getvalue().rstrip("\n").split("\n")[-1]
        assert f"Pearson chi2({df})" in line and f"{stat:.4f}" in line and f"Pr = {p:.3f}" in line


def test_percent_ties_round_half_up():
    # 3.125 prints as 3.13 and 96.875 as 96.88, where '%.2f' on the binary double gives 3.12 for the first
    from ose.commands.tab import pct2
    assert [pct2(x) for x in (3.125, 96.875, 0.0, 100.0, 12.346)] == \
        ["3.13", "96.88", "0.00", "100.00", "12.35"]
    it, out = mk([("v", rep([1, 2], [1, 31]), "v", "")])  # 1/32 = 3.125%
    it.dispatch("tab v")
    assert "3.13" in out.getvalue()


def test_two_way_if_in_and_missing():
    it, out = mk([("x", [1, 1, 2, 2, 2, 9], "x", ""), ("y", [0, 1, 0, 0, 1, 1], "y", "")])
    it.dispatch("tab x y if x<9")
    assert it.r["N"] == 5 and it.r["r"] == 2 and it.r["c"] == 2
    it.dispatch("tab x y in 1/3")
    assert it.r["N"] == 3
    it2, out2 = mk([("x", [1, 2, M.SYSMISS], "x", ""), ("y", [0, 0, 0], "y", "")])
    it2.dispatch("tab x y")
    assert it2.r["N"] == 2
    it2.dispatch("tab x y, missing")
    assert it2.r["N"] == 3 and it2.r["r"] == 3
    assert "\n         . |         1 |         1 \n" in out2.getvalue()


def test_two_way_zero_cells_and_dropped_categories():
    # an empty cell prints 0; a value with no observation in the used rows gets no row
    it, out = mk([("a", [1, 1, 3, 2], "a", ""), ("b", [1, 2, 1, 1], "b", "")])
    it.dispatch("tab a b if a!=2")
    t = out.getvalue()
    assert "         1 |         1          1 |         2 " in t
    assert "         3 |         1          0 |         1 " in t
    assert rows_of(t) == ["", "a", "1", "3", "Total"]


def test_two_way_unseen_layouts_refused():
    def run(cols, cmd, labels=None):
        it, out = mk(cols, labels)
        with pytest.raises(Unsupported):
            it.dispatch(cmd)
        assert out.getvalue() == ""
    ok = [1, 2, 1, 2]
    # a count of 1,000 or more (thousands separator never seen in a two-way table)
    run([("a", rep([1, 2], [1000, 5]), "a", ""), ("b", rep([1, 2], [1000, 5]), "b", "")], "tab a b")
    # a column variable with value labels (header text of a labelled column never seen)
    run([("a", ok, "a", ""), ("b", ok, "b", "l")], "tab a b", {"l": {1: "x", 2: "y"}})
    # more columns than fit in 86 characters (panel split never seen)
    run([("a", list(range(1, 9)), "a", ""), ("b", list(range(1, 9)), "b", "")], "tab a b")
    # a column label wider than the column block; a row label of three lines; a spaced row label that wraps
    run([("a", ok, "a", ""), ("b", ok, "a very long column variable label", "")], "tab a b")
    run([("averyveryveryverylongvariablename", ok, "", ""), ("b", ok, "b", "")], "tab averyveryveryverylongvariablename b")
    run([("a", ok, "two words that wrap here", ""), ("b", ok, "b", "")], "tab a b")
    # chi2 on a one-row table; non-integer values
    run([("a", [1, 1], "a", ""), ("b", [1, 2], "b", "")], "tab a b, chi2")
    run([("a", [1.5, 2.5], "a", ""), ("b", [1, 2], "b", "")], "tab a b")
    # a string wider than the stub minimum
    it = mk([("b", ok, "b", "")])[0]
    it.ds.add(Variable("s", "str12", np.array(["abcdefghijkl"] * 4, dtype=object)))
    with pytest.raises(Unsupported):
        it.dispatch("tab s b")


def test_two_way_errors():
    it, _ = mk([("a", [], "a", ""), ("b", [], "b", "")])
    with pytest.raises(StataError) as e:
        it.dispatch("tab a b")
    assert e.value.rc == 2000
