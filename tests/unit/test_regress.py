"""regress (vce(robust)), testparm, the line-width-dependent name column, rules .3 in the open harness.

Independent check for the numbers: least squares by numpy lstsq and the HC1 sandwich summed one
observation at a time (no shared code with engine/ose/commands/regress.py). The layout and every
printed digit are also checked on the authors' real data by the open case dv-3EDO2Y (173 tables).
"""
import io
import os
import sys

import numpy as np
import pytest
from scipy import stats as SS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "harness"))

from ose import commands  # noqa: E402,F401
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402
from ose.errors import Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402


def data(n=300, seed=7, names=("y", "x1", "x2", "g")):
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = (rng.random(n) > 0.5).astype(float)
    g = rng.integers(1, 4, size=n).astype(float)
    y = 0.4 * x1 - 0.2 * x2 + 0.3 * (g == 3) + rng.normal(size=n) * (1 + np.abs(x1))  # heteroskedastic
    return dict(zip(names, (y, x1, x2, g)))


def write(tmp_path, d):
    write_dta(Dataset([Variable(k, "double", v) for k, v in d.items()]), str(tmp_path / "d.dta"))


def run(src, tmp_path, linesize=None):
    p = tmp_path / "t.do"
    p.write_text(src)
    out = io.StringIO()
    it = Interp(cwd=str(tmp_path), out=out)
    if linesize:
        it.settings["linesize"] = str(linesize)
    it.run_file(str(p))
    return it, out.getvalue()


def hc1(y, X):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    N, k = X.shape
    meat = np.zeros((k, k))
    for i in range(N):
        meat += e[i] ** 2 * np.outer(X[i], X[i])
    bread = np.linalg.inv(X.T @ X)
    return b, bread @ meat @ bread * N / (N - k), e


def test_regress_robust_numbers_match_independent_hc1(tmp_path):
    d = data()
    write(tmp_path, d)
    it, out = run("use d, clear\nreg y x1 x2 i.g, vce(robust)\n", tmp_path)
    X = np.column_stack([d["x1"], d["x2"], d["g"] == 2, d["g"] == 3, np.ones(len(d["y"]))]).astype(float)
    b, V, e = hc1(d["y"], X)
    assert it.e["_colnames"] == ["x1", "x2", "2.g", "3.g", "_cons"]
    np.testing.assert_allclose(it.e["_b"], b, rtol=1e-10)
    np.testing.assert_allclose(it.e["V"], V, rtol=1e-9)
    N, k = X.shape
    F = b[:-1] @ np.linalg.solve(V[:-1, :-1], b[:-1]) / (k - 1)
    assert it.e["F"] == pytest.approx(F, rel=1e-9)
    r2 = 1 - (e @ e) / np.sum((d["y"] - d["y"].mean()) ** 2)
    assert it.e["r2"] == pytest.approx(r2, rel=1e-12)
    assert it.e["df_r"] == N - k and it.e["rmse"] == pytest.approx(np.sqrt(e @ e / (N - k)), rel=1e-12)
    lines = out.splitlines()
    assert "Linear regression                               Number of obs     =        300" in lines
    assert f"                                                F(4, 295)         ={it.e['F']:>11.2f}" in lines
    assert any(ln.startswith("          x1 |") for ln in lines)          # 12-wide name column
    assert "           g |" in lines and "          2  |" in lines[lines.index("           g |") + 1]
    assert lines[lines.index("           g |") + 3] == " " * 13 + "|"   # separator closes the factor group


def test_testparm_wald_f_and_layout(tmp_path):
    d = data()
    write(tmp_path, d)
    it, out = run("use d, clear\nreg y x1 x2 i.g, robust\ntestparm x1 x2\n", tmp_path)
    X = np.column_stack([d["x1"], d["x2"], d["g"] == 2, d["g"] == 3, np.ones(len(d["y"]))]).astype(float)
    b, V, _ = hc1(d["y"], X)
    F = b[:2] @ np.linalg.solve(V[:2, :2], b[:2]) / 2
    assert it.r["F"] == pytest.approx(F, rel=1e-9)
    assert it.r["p"] == pytest.approx(SS.f.sf(F, 2, 295), rel=1e-9)
    lines = out.splitlines()
    tail = lines[lines.index(" ( 1)  x1 = 0"):]
    assert tail[0] == " ( 1)  x1 = 0" and tail[1] == " ( 2)  x2 = 0" and tail[2] == ""
    assert tail[3] == f"       F(  2,   295) ={F:8.2f}"
    assert tail[4].startswith("            Prob > F =") and len(tail[4]) == 32


def test_name_column_widens_on_a_wide_session(tmp_path):
    # As in 3EDO2Y (linesize 105): column = longest row label (20); depvar abbreviated to it; rule 86 wide.
    # Names are ours: a 25-character depvar and a 20-character regressor.
    d = data(names=("respondents_trust_council", "shown_campaign_ad_01", "x2", "survey"))
    write(tmp_path, d)
    it, out = run("use d, clear\nreg respondents_trust_council shown_campaign_ad_01 x2 i.survey, vce(robust)\n",
                  tmp_path, linesize=105)
    lines = out.splitlines()
    assert "-" * 86 in lines
    assert any(ln.startswith("respondents_trust_~l | Coefficient") for ln in lines)
    assert any(ln.startswith("shown_campaign_ad_01 |") for ln in lines)
    assert any(ln.startswith("                  2  |") for ln in lines)


def test_name_column_abbreviates_on_a_narrow_session(tmp_path):
    # As in HNPXO1 (linesize 80): 15-character names are shown as first10~last in a 12-wide column. Name is ours.
    d = data(names=("y", "lnplantcapacity", "x2", "g"))
    write(tmp_path, d)
    _, out = run("use d, clear\nreg y lnplantcapacity x2, vce(robust)\n", tmp_path)
    assert any(ln.startswith("lnplantcap~y |") for ln in out.splitlines())


def test_name_column_between_witnessed_cases_is_refused(tmp_path):
    d = data(names=("y", "abcdefghijklm", "x2", "g"))   # 13 characters at linesize 80: not pinned
    write(tmp_path, d)
    with pytest.raises(Unsupported):
        run("use d, clear\nreg y abcdefghijklm x2, vce(robust)\n", tmp_path)


@pytest.mark.parametrize("cmd", ["reg y x1 [aw=x2]", "reg y x1 [aw=x2], robust",
                                 "reg y x1, robust noconstant", "testparm i.g", "testparm c.x1#i.g"])
def test_unpinned_regress_shapes_fail_loudly(tmp_path, cmd):
    write(tmp_path, data())
    with pytest.raises(Unsupported):
        run(f"use d, clear\nreg y x1 x2, robust\n{cmd}\n" if cmd.startswith("testparm") else
            f"use d, clear\n{cmd}\n", tmp_path)


def test_regress_thousands_in_header(tmp_path):
    # As in 9N6PBH: thousands separators in the header count and in the cluster note line.
    write(tmp_path, data(n=1200))
    _, out = run("use d, clear\nreg y x1, robust\n", tmp_path)
    assert "Number of obs     =      1,200" in out


def test_echo_wraps_at_linesize_minus_one(tmp_path):
    write(tmp_path, data())
    cmd = "count if " + " | ".join(["x1 > 100"] * 12)
    _, out80 = run(f"use d, clear\n{cmd}\n", tmp_path)
    _, out105 = run(f"use d, clear\n{cmd}\n", tmp_path, linesize=105)
    assert max(len(x) for x in out80.splitlines()) == 79
    assert max(len(x) for x in out105.splitlines()) == 104


def test_rules_3_tempfile_and_wording(tmp_path):
    import logmatch as L
    assert L.MATCH_RULES_VERSION == "2026-11-24.14.7"
    # The wording table is shared data (harness/wording-table.tsv or OSE_WORDING_TABLE); this uses the merge entry.
    exp, act = "    not matched                             0", "    Not matched                             0"
    assert L.line_cmp(exp, act)[0]                  # headline: wording table
    assert not L.line_cmp(exp, act, strict=True)[0]  # strict: wording still a miss
    assert L.line_cmp("file /var/folders/ab/T//St40864.000001 saved", "file /tmp/w/oses8bdwav3.tmp saved")[0]
    assert L.line_cmp("(file /x/T/St1.000001 not found)", "(file /y/ose1a.tmp not found)", strict=True)[0]
    assert not L.line_cmp("file /a/b.dta saved", "file /c/b.dta saved")[0]   # other paths stay exact


# ---- one-way clustered errors, lincom, factor testparm, value-label layout (9N6PBH) ----

def cluster_sandwich(y, X, g):
    """Independent CR1: scores summed cluster by cluster in a Python loop, then the
    G/(G-1)*(N-1)/(N-k) factor (Cameron and Miller 2015, the CR1 small-sample factor)."""
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    N, k = X.shape
    meat = np.zeros((k, k))
    groups = sorted(set(g.tolist()))
    for gv in groups:
        idx = [i for i in range(N) if g[i] == gv]
        u = sum(X[i] * e[i] for i in idx)
        meat += np.outer(u, u)
    G = len(groups)
    bread = np.linalg.inv(X.T @ X)
    return b, bread @ meat @ bread * G / (G - 1) * (N - 1) / (N - k), G


def clustered(n=400, G=40, seed=11):
    rng = np.random.default_rng(seed)
    cl = rng.integers(1, G + 1, size=n).astype(float)
    ce = rng.normal(size=G + 1)[cl.astype(int)]
    x1 = rng.normal(size=n) + 0.5 * ce
    x2 = rng.normal(size=n)
    y = 0.3 * x1 - 0.1 * x2 + ce + rng.normal(size=n)
    return {"y": y, "x1": x1, "x2": x2, "cl": cl}


def test_cluster_matches_independent_cr1_and_prints_the_note(tmp_path):
    d = clustered()
    write(tmp_path, d)
    it, out = run("use d, clear\nreg y x1 x2, cl(cl)\n", tmp_path)
    X = np.column_stack([d["x1"], d["x2"], np.ones(len(d["y"]))])
    b, V, G = cluster_sandwich(d["y"], X, d["cl"])
    assert np.allclose(it.e["_b"], b, rtol=0, atol=1e-10)
    assert np.allclose(it.e["V"], V, rtol=1e-9, atol=0)
    assert it.e["df_r"] == G - 1 and it.e["N_clust"] == G
    F = b[:2] @ np.linalg.solve(V[:2, :2], b[:2]) / 2
    assert abs(it.e["F"] - F) < 1e-9 * F
    lines = out.splitlines()
    assert f"F(2, {G - 1})" in out
    k = next(i for i, ln in enumerate(lines) if "Std. err. adjusted" in ln)
    assert lines[k] == f"(Std. err. adjusted for {G} clusters in cl)".rjust(78)   # table width 12+66
    assert lines[k + 1] == "-" * 78 and lines[k + 2].endswith("Robust")
    # t, p and the interval use G-1 degrees of freedom
    se = np.sqrt(V[0, 0])
    row = next(ln for ln in lines if ln.startswith("          x1 |"))
    assert row.split()[5] == f"{2 * SS.t.sf(abs(b[0] / se), G - 1):.3f}"


@pytest.mark.parametrize("opt", ["cluster(cl)", "vce(cluster cl)", "vce(cl cl)", "robust cluster(cl)"])
def test_cluster_spellings(tmp_path, opt):
    write(tmp_path, clustered())
    it, _ = run(f"use d, clear\nreg y x1 x2, {opt}\n", tmp_path)
    assert it.e["vce"] == "cluster"


def test_lincom_is_cb_with_cluster_df(tmp_path):
    d = clustered()
    write(tmp_path, d)
    it, out = run("use d, clear\nreg y x1 x2, cl(cl)\nlincom x1-x2\n", tmp_path)
    X = np.column_stack([d["x1"], d["x2"], np.ones(len(d["y"]))])
    b, V, G = cluster_sandwich(d["y"], X, d["cl"])
    c = np.array([1.0, -1.0, 0.0])
    assert abs(it.r["estimate"] - c @ b) < 1e-10
    assert abs(it.r["se"] - np.sqrt(c @ V @ c)) < 1e-10
    assert it.r["df"] == G - 1
    lines = out.splitlines()
    assert " ( 1)  x1 - x2 = 0" in lines
    assert any(ln.startswith("           y | Coefficient  Std. err.") for ln in lines)
    assert any(ln.startswith("         (1) |") for ln in lines)


def labelled(n=600, seed=5):
    rng = np.random.default_rng(seed)
    a = rng.integers(1, 4, size=n).astype(float)
    h = rng.integers(0, 2, size=n).astype(float)
    cl = rng.integers(1, 61, size=n).astype(float)
    y = 0.2 * (a == 2) - 0.1 * h + 0.15 * (a == 3) * h + rng.normal(size=n)
    return Dataset([Variable("y", "double", y), Variable("tax", "double", a, vlabel="tax"),
                    Variable("inc", "double", h, vlabel="inc"), Variable("cl", "double", cl)],
                   value_labels={"tax": {1.0: "Payroll", 2.0: "Payroll and VAT", 3.0: "Payroll and sales taxes"},
                                 "inc": {0.0: "base", 1.0: "upper-bracket"}})


def test_value_labels_cap_the_column_and_interactions_take_two_lines(tmp_path):
    # As in 9N6PBH at linesize 90: a 23-character value label caps the column at 90-67 = 23 and is cut to its
    # first 20 characters and `..`; interaction rows print `label #|` then the second factor's line. Labels are ours.
    write_dta(labelled(), str(tmp_path / "d.dta"))
    it, out = run("use d, clear\nreg y ib1.tax##i.inc, cl(cl)\ntestparm i.tax#i.inc\n", tmp_path, linesize=90)
    lines = out.splitlines()
    assert "-" * 89 in lines
    assert any(ln.startswith("Payroll and sales ta..  |") for ln in lines)
    assert "       Payroll and VAT #|" in lines
    assert any(ln.startswith("         upper-bracket  |") for ln in lines)
    assert "                tax#inc |" in lines
    assert " ( 1)  2.tax#1.inc = 0" in lines and " ( 2)  3.tax#1.inc = 0" in lines


def test_value_labels_widen_when_the_table_stays_inside(tmp_path):
    # As in 9N6PBH: an 18-wide column (84-column table at linesize 90) widens; here the longest need is
    # a 15-character label + indent = 16, so an 82-column table with labels uncut.
    ds = labelled()
    ds.value_labels["tax"][3.0] = "Flat sales tax"
    write_dta(ds, str(tmp_path / "d.dta"))
    _, out = run("use d, clear\nreg y i.tax, cl(cl)\n", tmp_path, linesize=90)
    lines = out.splitlines()
    assert "-" * 82 in lines and any(ln.startswith(" Flat sales tax  |") for ln in lines)


def test_display_shows_eight_significant_digits(tmp_path):
    # As in 9N6PBH, where `di r(p)` prints p values in the 10-wide general format. Values are ours.
    write(tmp_path, data())
    _, out = run("display .7316248509\ndisplay .004183772\n", tmp_path)
    assert ".73162485" in out.splitlines() and ".00418377" in out.splitlines()


# ---- plain (unadjusted) regress: the ANOVA header (5T2U2K) ----

def test_plain_regress_matches_classical_ols_and_prints_the_anova_block(tmp_path):
    d = data(n=1200)
    write(tmp_path, d)
    it, out = run("use d, clear\nreg y x1 x2\n", tmp_path)
    X = np.column_stack([d["x1"], d["x2"], np.ones(1200)])
    b = np.linalg.lstsq(X, d["y"], rcond=None)[0]
    e = d["y"] - X @ b
    rss = float(e @ e)
    tss = float(((d["y"] - d["y"].mean()) ** 2).sum())
    V = np.linalg.inv(X.T @ X) * rss / (1200 - 3)
    assert np.allclose(it.e["_b"], b, atol=1e-10) and np.allclose(it.e["V"], V, rtol=1e-9)
    Fclassic = ((tss - rss) / 2) / (rss / 1197)          # the ANOVA ratio, computed without V
    assert abs(it.e["F"] - Fclassic) < 1e-9 * Fclassic
    assert abs(it.e["r2_a"] - (1 - (rss / 1197) / (tss / 1199))) < 1e-12
    lines = out.splitlines()
    k = lines.index(next(ln for ln in lines if ln.startswith("      Source |")))
    assert lines[k].endswith("Number of obs   =     1,200") and len(lines[k]) == 78
    assert lines[k + 1].startswith("-------------+----------------------------------   F(2, 1197)      =")
    assert lines[k + 3].startswith("    Residual |") and "     1,197" in lines[k + 3]
    assert lines[k + 5].startswith("       Total |") and "     1,199" in lines[k + 5]
    assert lines[k + 7] == "-" * 78
    assert lines[k + 8].startswith("           y | Coefficient  Std. err.")   # no title row, capital S


def test_regress_anova_cells_use_nine_significant_digits(tmp_path):
    from ose.commands.regress import _ss
    assert _ss(347.2918064) == "347.291806" and _ss(0.2381904436) == ".238190444"
    assert _ss(5306.27410) == "5306.2741"
    with pytest.raises(Unsupported):
        _ss(2.5e9)
