"""reghdfe: partialling, singletons, absorbed DoF, factor variables, table layout.

The independent check is an explicit dummy-matrix least-squares fit (every
fixed-effect level as a column, solved by numpy lstsq), which shares no code
with the alternating-projection path (Frisch-Waugh-Lovell: same slopes).
"""
import io
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from ose import commands  # noqa: E402,F401
from ose import hdfe as H  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402
from ose.errors import Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402


def panel(seed=1, n_firm=60, n_year=8):
    rng = np.random.default_rng(seed)
    firm = np.repeat(np.arange(n_firm), n_year)
    year = np.tile(np.arange(n_year), n_firm)
    region = firm % 7                        # firms nested in regions
    ind_year = (firm % 5) * 100 + year       # industry-by-year cells
    keep = rng.random(len(firm)) > 0.15      # unbalanced
    firm, year, region, ind_year = firm[keep], year[keep], region[keep], ind_year[keep]
    x1 = rng.normal(size=len(firm))
    g = rng.integers(1, 4, size=len(firm))   # factor with levels 1..3
    y = 0.5 * x1 - 0.3 * (g == 2) + 0.8 * (g == 3) + 0.1 * firm % 3 + 0.05 * year + rng.normal(size=len(firm))
    return dict(y=y, x1=x1, g=g.astype(float), firm=firm.astype(float), year=year.astype(float),
                ind_year=ind_year.astype(float), region=region.astype(float))


def dummies(codes):
    D = np.zeros((len(codes), codes.max() + 1))
    D[np.arange(len(codes)), codes] = 1
    return D


def test_partial_matches_dummy_regression():
    d = panel()
    fes = [H.codes(d["firm"]), H.codes(d["ind_year"])]
    X = np.column_stack([d["x1"], d["g"] == 2, d["g"] == 3]).astype(float)
    Z, iters = H.Absorber(fes).partial(np.column_stack([d["y"], X]))
    b = np.linalg.lstsq(Z[:, 1:], Z[:, 0], rcond=None)[0]
    full = np.column_stack([X] + [dummies(f) for f in fes])
    bd = np.linalg.lstsq(full, d["y"], rcond=None)[0][:3]
    assert iters > 1
    assert np.max(np.abs(b - bd)) < 1e-6


def test_singletons_dropped_repeatedly():
    a = np.array([0, 0, 1, 1, 2, 3, 3])
    b = np.array([0, 1, 0, 1, 1, 2, 2])
    # obs 4 is a singleton in a; after it goes nothing else changes
    keep = H.drop_singletons([a, b])
    assert keep.tolist() == [True, True, True, True, False, True, True]
    # chain: removing one singleton creates another
    a = np.array([0, 0, 1, 2, 2])
    b = np.array([0, 1, 1, 2, 2])
    keep = H.drop_singletons([a, b])
    assert keep.tolist() == [False, False, False, True, True]


def test_absorbed_dof_rules():
    d = panel()
    firm, iy, region = H.codes(d["firm"]), H.codes(d["ind_year"]), H.codes(d["region"])
    # firm nested in cluster=firm: fully redundant; first other FE loses one to the constant
    rows = H.absorbed_dof([firm, iy], firm)
    assert rows[0] == [firm.max() + 1, firm.max() + 1, 0, "*"]
    assert rows[1][1] == 1 and rows[1][3] == ""
    # no nesting: first FE keeps all levels, second loses its connected components with the first
    rows = H.absorbed_dof([firm, iy], H.codes(d["g"]))
    assert rows[0][1] == 0
    assert rows[1][1] == H.components(firm, iy)
    # third non-nested FE: largest component count against earlier ones, marked '?'
    rows = H.absorbed_dof([firm, iy, H.codes(d["year"])], H.codes(d["g"]))
    assert rows[2][3] == "?"


def write_panel(tmp_path):
    d = panel()
    n = len(d["y"])
    vars_ = [Variable(k, "double", d[k].astype(float)) for k in ("y", "x1", "g", "firm", "year", "ind_year", "region")]
    ds = Dataset(vars_)
    write_dta(ds, str(tmp_path / "p.dta"))
    return n


def run(src, tmp_path):
    p = tmp_path / "t.do"
    p.write_text(src)
    out = io.StringIO()
    it = Interp(cwd=str(tmp_path), out=out)
    it.run_file(str(p))
    return it, out.getvalue()


def test_reghdfe_command_coefficients_and_cluster_se(tmp_path):
    write_panel(tmp_path)
    it, out = run("use p, clear\nreghdfe y x1 i.g, absorb(firm ind_year) cluster(firm)\nest store m1\n", tmp_path)
    d = panel()
    fes = [H.codes(d["firm"]), H.codes(d["ind_year"])]
    X = np.column_stack([d["x1"], d["g"] == 2, d["g"] == 3]).astype(float)
    full = np.column_stack([X, np.ones(len(d["y"]))] + [dummies(f)[:, 1:] for f in fes])
    beta = np.linalg.lstsq(full, d["y"], rcond=None)[0]   # minimum-norm; slopes are identified
    e = d["y"] - full @ beta
    b = it.e["_b"]
    assert np.max(np.abs(b[:3] - beta[:3])) < 1e-6
    # CR1 sandwich on the slopes, written out independently on the dummy design
    N, G = len(e), fes[0].max() + 1
    bread = np.linalg.pinv(full.T @ full)
    sc = np.zeros((G, full.shape[1]))
    np.add.at(sc, fes[0], full * e[:, None])
    # DoF: firm nested in the cluster, so its levels are not counted; ind_year loses one to the constant
    K = (H.codes(d["ind_year"]).max() + 1 - 1) + 3 + 1
    V = bread @ sc.T @ sc @ bread * (N - 1) / (N - K) * G / (G - 1)
    se = np.sqrt(np.diag(V))[:3]
    se_engine = np.sqrt(np.diag(it.e["V"]))[:3]
    assert np.max(np.abs(se_engine / se - 1)) < 1e-6
    assert "HDFE Linear regression" in out
    assert "(Std. err. adjusted for" in out
    assert "m1" in it.estimates


def test_table_layout_factor_groups(tmp_path):
    write_panel(tmp_path)
    _, out = run("use p, clear\nreghdfe y x1 i.g, absorb(firm ind_year) cluster(firm)\n", tmp_path)
    lines = out.splitlines()
    k = next(i for i, s in enumerate(lines) if s.startswith("          x1 |"))
    # continuous row, then a blank separator, then the factor group header and its levels
    assert lines[k + 1] == "             |"
    assert lines[k + 2] == "           g |"
    assert lines[k + 3].startswith("          2  |")
    assert lines[k + 4].startswith("          3  |")
    assert lines[k + 5] == "             |"   # a factor group is closed by a separator (HNPXO1 a13, ownership)
    assert lines[k + 6].startswith("       _cons |")


def test_lone_slope_matches_dummy_regression(tmp_path):
    d = panel()
    firm = d["firm"].astype(int)
    industry_year = d["ind_year"].astype(int)
    year = d["year"].astype(int)
    rng = np.random.default_rng(57)
    d["x"] = rng.normal(size=firm.max() + 1)[firm]
    levels = np.unique(year)
    slopes = (year[:, None] == levels[:-1]) * d["x"][:, None]
    d["y"] += slopes @ rng.normal(size=len(levels) - 1)
    ds = Dataset([Variable(name, "double", values) for name, values in d.items()])
    write_dta(ds, str(tmp_path / "slopes.dta"))

    full = np.column_stack([slopes, dummies(firm), dummies(industry_year)])
    expected = np.linalg.lstsq(full, d["y"], rcond=None)[0][:len(levels) - 1]
    for term in ("c.x#i.year", "i.year#c.x"):
        it, out = run(f"use slopes, clear\nreghdfe y {term}, absorb(firm ind_year) cluster(firm)\n",
                      tmp_path)
        assert it.e["_colnames"] == [f"{v}.year#c.x" for v in levels] + ["_cons"]
        np.testing.assert_allclose(it.e["_b"][:-2], expected, atol=1e-6, rtol=0)
        assert it.e["df_m"] == len(levels) - 1
        assert it.e["_b"][-2] == 0
        assert np.count_nonzero(it.e["V"][-2]) == 0
        assert f"note: {levels[-1]}.year#c.x omitted because of collinearity" in out
        assert "        year#|\n         c.x |" in out
        assert f"{levels[-1]:>11}  |          0  (omitted)" in out

    with pytest.raises(Unsupported, match="regressors collinear with each other"):
        run("use slopes, clear\ngenerate double duplicate = x*(year==0)\n"
            "reghdfe y duplicate c.x#i.year, absorb(firm ind_year) cluster(firm)\n", tmp_path)


def test_unsupported_configurations_fail_loudly(tmp_path):
    write_panel(tmp_path)
    for cmd in ("reghdfe y x1, absorb(firm ind_year)",            # no clustering: layout not pinned
                "reghdfe y x1, absorb(firm) cluster(firm)",        # one FE: not pinned
                "reghdfe y x1, absorb(firm ind_year) vce(robust)",   # robust layout not pinned
                "reghdfe y c.x1#i.year, absorb(firm ind_year) cluster(firm)",  # x1 varies within FEs
                "reghdfe y i.g#i.year, absorb(firm ind_year) cluster(firm)",  # two-factor lone interaction
                "regress y c.x1#i.year"):                         # other estimator
        with pytest.raises(Exception) as ei:
            run(f"use p, clear\n{cmd}\n", tmp_path)
        assert "not implemented" in str(ei.value)


def test_dof_rule_nested_and_not():
    from ose.commands.estimation import dof_rule
    # The two cases HNPXO1 shows (a05: the cluster variable is nested in no absorbed effect; 02_table2: it is),
    # with counts of ours. Rows: levels, redundant, coefficients, nested mark.
    # Nothing nested -> K = df_a + k; RMSE df = N - k - df_a, with df_a = 3170 + 352 + 85 = 3607.
    rows = [[3170, 0, 3170, ""], [356, 4, 352, ""], [97, 12, 85, "?"]]
    assert dof_rule(rows, 21843, 5) == (3607 + 5, 21843 - 5 - 3607)
    # First effect nested in the cluster -> constant counted once; RMSE df also drops its levels; df_a = 370 + 85.
    rows = [[4105, 4105, 0, "*"], [371, 1, 370, ""], [97, 12, 85, ""]]
    assert dof_rule(rows, 19628, 3) == (455 + 3 + 1, 19628 - 3 - 455 - 4105)


def test_continuation_into_star_comment_is_a_comment():
    # Witnessed in doi:10.7910/DVN/HNPXO1 06_table6_alternative_outcomes.do: a `///` line with trailing text
    # continues into a `*` comment line, and the log shows no error. Lines here are ours.
    from ose.lexer import logical_lines
    lines = logical_lines("display 1\n///alt\n*Second block\ndisplay 2\n")
    texts = [ln.text for ln in lines]
    assert texts[:3] == ["display 1", "", "display 2"]
    assert lines[1].raw == ["///alt", "*Second block"]


# The rule HNPXO1 logs show (15- and 18-character names in a 12-wide column), on names of ours.
@pytest.mark.parametrize("name,shown", [("site_permit_dum", "site_permi~m"), ("lnplantcapacity", "lnplantcap~y"),
                                        ("treated_stormwater", "treated_st~r"), ("lnworkdays", "lnworkdays")])
def test_name_abbreviation_rule_seen_in_published_logs(name, shown):
    from ose.table import abbrev
    assert abbrev(name) == shown


@pytest.mark.parametrize("factor,labels,base_label,base_position", [
    ("i.g", 'label define group 1 "Partly-public-firm"\nlabel values g group\n', "Partly-pu~m", 1),
    ("ib2.g", "", "2", 2),
])
def test_allbaselevels_shows_base_and_omitted_rows_without_changing_results(
    tmp_path, factor, labels, base_label, base_position
):
    write_panel(tmp_path)
    cmd = f"reghdfe y x1 {factor} i.fixed, absorb(firm ind_year) cluster(firm)"
    it, out = run(f"use p, clear\n{labels}generate fixed = mod(firm, 2)\n"
                  f"{cmd}\nestimates store plain\n{cmd} allbaselevels\n", tmp_path)
    plain_out, with_bases = out.split(f". {cmd} allbaselevels\n")
    assert "(base)" not in plain_out
    lines = with_bases.splitlines()
    g = lines.index("           g |")
    assert lines[g + base_position] == f"{base_label:>11}  |          0  (base)"
    fixed = lines.index("       fixed |")
    assert lines[fixed + 1:fixed + 3] == [
        "          0  |          0  (base)",
        "          1  |          0  (omitted)",
    ]
    assert "(omitted)" in plain_out
    assert it.e.keys() == it.estimates["plain"].keys()
    for key, value in it.e.items():
        np.testing.assert_equal(value, it.estimates["plain"][key], err_msg=key)
