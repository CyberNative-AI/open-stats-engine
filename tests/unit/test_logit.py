"""logit: numbers against an independent IRLS, the step rule, layout, refusals, and the authors' real blocks.

Independent check for the numbers: iteratively reweighted least squares (weighted `lstsq` per iteration,
the covariance from the final weighted cross-product) written here, sharing no code with
engine/ose/commands/logit.py, run to 1e-13. The layout and every printed digit are also checked on the
authors' real data: the 8 `logit` blocks of open-list package 5T2U2K (Replication.log), skipped when the
cache is absent.
"""
import io
import os
import re
import sys

import numpy as np
import pytest
from scipy import stats as SS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "harness"))

from ose import commands  # noqa: E402,F401
from ose.commands.logit import newton  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402
from ose.errors import Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402

CACHE = os.environ.get("OSE_CACHE", os.path.expanduser("~/.cache/open-stats-engine"))


def data(n=900, seed=11, effect=1.2, share=0.17):
    rng = np.random.default_rng(seed)
    t = (rng.random(n) < share).astype(float)
    x = rng.normal(size=n)
    g = rng.integers(1, 4, size=n).astype(float)
    eta = 1.9 + effect * t + 0.3 * x - 0.4 * (g == 3)
    y = (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(float)
    return dict(y=y, t=t, x=x, g=g)


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


def irls(y, X, iters=200):
    """Weighted least squares on the working response, to machine precision. Returns b, V, ll."""
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = X @ b
        p = 1 / (1 + np.exp(-eta))
        w = p * (1 - p)
        z = eta + (y - p) / w
        sw = np.sqrt(w)
        b = np.linalg.lstsq(X * sw[:, None], z * sw, rcond=None)[0]
    eta = X @ b
    p = 1 / (1 + np.exp(-eta))
    w = p * (1 - p)
    V = np.linalg.inv((X * w[:, None]).T @ X)
    ll = float(np.sum(np.where(y == 1, np.log(p), np.log(1 - p))))
    return b, V, ll


def test_numbers_match_independent_irls_and_stored_results(tmp_path):
    d = data()
    write(tmp_path, d)
    it, out = run("use d, clear\nlogit y t x i.g\n", tmp_path)
    X = np.column_stack([d["t"], d["x"], d["g"] == 2, d["g"] == 3, np.ones(len(d["y"]))]).astype(float)
    b, V, ll = irls(d["y"], X)
    assert np.allclose(it.e["_b"], b, atol=1e-8, rtol=0) and np.allclose(it.e["V"], V, atol=1e-9, rtol=1e-7)
    ybar = d["y"].mean()
    N = len(d["y"])
    ll0 = N * (ybar * np.log(ybar) + (1 - ybar) * np.log(1 - ybar))        # closed form, no iteration
    assert abs(it.e["ll"] - ll) < 1e-9 and abs(it.e["ll_0"] - ll0) < 1e-9
    assert abs(it.e["chi2"] - 2 * (ll - ll0)) < 1e-8 and it.e["df_m"] == 4 and it.e["N"] == N
    assert abs(it.e["r2_p"] - (1 - ll / ll0)) < 1e-12 and it.e["converged"] == 1
    se = np.sqrt(np.diag(V))
    zc = SS.norm.ppf(0.975)
    assert abs(it.e["V"][0, 0] ** 0.5 - se[0]) < 1e-8
    # a z row is printed from b/se and the normal tail
    row = next(ln for ln in out.splitlines() if ln.lstrip().startswith("t |"))
    assert f"{b[0] / se[0]:.2f}" in row and f"{2 * SS.norm.sf(abs(b[0] / se[0])):.3f}" in row
    assert abs(b[0] - zc * se[0]) < 10


def test_layout_iteration_log_header_and_z_table(tmp_path):
    d = data()
    write(tmp_path, d)
    it, out = run("use d, clear\nlogit y t\n", tmp_path)
    lines = out.splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("Iteration 0:"))
    assert re.fullmatch(r"Iteration \d+:   log likelihood = +-?[\d.]+  ", lines[k])
    assert lines[k - 1] == ""
    n_it = len([ln for ln in lines if ln.startswith("Iteration ")])
    h = k + n_it + 1
    assert lines[h].startswith("Logistic regression" + " " * 37 + "Number of obs = ")
    assert lines[h + 1].startswith(" " * 56 + "LR chi2(1)    = ")
    assert lines[h + 2].startswith(" " * 56 + "Prob > chi2   = ")
    assert lines[h + 3].startswith("Log likelihood = ") and lines[h + 3][56:].startswith("Pseudo R2     = ")
    assert len(lines[h]) == 56 + 13 + 3 + 6
    assert lines[h + 5] == "-" * 78
    assert lines[h + 6] == "           y | Coefficient  Std. err.      z    P>|z|     [95% conf. interval]"
    # convergence rule: the last move is below 1e-7 relative and the one before it is not (the printed values
    # may or may not repeat: that depends on the size of the last move against the printed digits)
    X = np.column_stack([d["t"], np.ones(len(d["y"]))])
    _, _, lls, conv = newton(X, d["y"])
    assert conv and len(lls) == n_it
    assert abs(lls[-1] - lls[-2]) < 1e-7 * abs(lls[-1]) <= abs(lls[-2] - lls[-3])


def test_step_rule_two_expands_by_eighths_while_the_log_likelihood_rises():
    d = data(n=1600, effect=1.3, share=0.15)
    X = np.column_stack([d["t"], np.ones(len(d["y"]))])
    b2, _, l2, c2 = newton(X, d["y"])                       # rule 2 (default)
    b1, _, l1, c1 = newton(X, d["y"], expand=False)         # rule 1: plain full step
    assert c1 and c2 and l1[0] == l2[0]
    assert l2[1] > l1[1] + 1e-3                              # the expansion pays at iteration 1
    assert np.allclose(b1, b2, atol=1e-5) and len(l2) <= len(l1)
    # the step length is a multiple of 1/8 along the Newton direction
    p0 = np.full(len(d["y"]), d["y"].mean())
    step = np.linalg.solve((X * (p0 * (1 - p0))[:, None]).T @ X, X.T @ (d["y"] - p0))
    b0 = np.array([0.0, np.log(d["y"].mean() / (1 - d["y"].mean()))])

    def ll(b):
        return float(np.sum(d["y"] * (X @ b) - np.logaddexp(0, X @ b)))
    best = max(range(8, 25), key=lambda m: ll(b0 + m / 8 * step))
    assert abs(ll(b0 + best / 8 * step) - l2[1]) < 1e-9


@pytest.mark.parametrize("cmd", [
    "logit y t x, robust", "logit y t x, vce(robust)", "logit y t x, cl(g)", "logit y t x, vce(cluster g)",
    "logit y t x, or", "logit y t x, offset(x)", "logit y t x, noconstant", "logit y t x [fweight=g]",
    "logit y t x, level(90)",
])
def test_unpinned_logit_shapes_fail_loudly(tmp_path, cmd):
    write(tmp_path, data())
    with pytest.raises(Unsupported):
        run(f"use d, clear\n{cmd}\n", tmp_path)


def test_refusals_for_outcomes_collinearity_and_perfect_prediction(tmp_path):
    d = data()
    d["z"] = d["x"] * 2.0
    d["w"] = np.where(d["g"] == 3, 1.0, d["y"] * 0)            # w != 0 only where g == 3: predicts nothing
    d["perfect"] = (d["y"] == 0).astype(float)                   # non-zero exactly when y == 0
    d["y3"] = d["g"]
    write(tmp_path, d)
    for cmd in ("logit y3 t", "logit y x z", "logit y t perfect"):
        with pytest.raises(Unsupported):
            run(f"use d, clear\n{cmd}\n", tmp_path)


def test_sample_follows_if_and_missing(tmp_path):
    d = data()
    d["x"] = d["x"].copy()
    d["x"][:10] = 8.98846567431158e307            # .
    write(tmp_path, d)
    it, out = run("use d, clear\nlogit y t x if g != 2\n", tmp_path)
    n = int(((d["g"] != 2) & (d["x"] < 1e300)).sum())
    assert it.e["N"] == n and f"Number of obs = {n:>6,}" in out


def test_name_column_widens_for_a_13_character_dependent_variable(tmp_path):
    d = data()
    d["outcome_final"] = d.pop("y")
    write(tmp_path, d)
    it, out = run("use d, clear\nlogit outcome_final t\n", tmp_path, linesize=99)
    lines = out.splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("outcome_final |"))
    assert lines[k - 1] == "-" * 79 and lines[k + 1] == "-" * 14 + "+" + "-" * 64


CASE = os.path.join(os.path.dirname(__file__), "..", "cases", "open", "dv-5T2U2K-Replication.json")


def _pins():
    """The data file and the expected log with the SHA-256 pins of the open case (case provenance contract)."""
    import json
    case = json.load(open(CASE))
    data = next(f for f in case["files"] if f["file_id"] == 7240173)
    return [(os.path.join(CACHE, "dataverse", "7240173.orig"), data["sha256"]),
            (os.path.join(CACHE, "dataverse", str(case["expected_log"]["file_id"])), case["expected_log"]["sha256"])]


def _verified(pins):
    """Fails if any present input does not match its pin; then None if any input is absent (offline skip).
    Every present file is checked first, so a missing partner cannot hide a corrupt cached file."""
    import hashlib
    for p, want in pins:
        if os.path.exists(p):
            got = hashlib.sha256(open(p, "rb").read()).hexdigest()
            assert got == want, f"{os.path.basename(p)}: sha256 {got} does not match the case pin {want}"
    if not all(os.path.exists(p) for p, _ in pins):
        return None
    return [p for p, _ in pins]


def _real_blocks():
    paths = _verified(_pins())
    if paths is None:
        return None, None
    dta, log = paths
    L = open(log, errors="replace").read().split("\n")
    out = []
    for i, ln in enumerate(L):
        if not re.match(r"^\. logit\b", ln):
            continue
        j = i + 1
        block = []
        while j < len(L) and not L[j].startswith(". "):
            block.append(L[j])
            j += 1
        while block and block[-1] == "":
            block.pop()
        out.append((ln[2:].rstrip().rstrip(","), block))
    return dta, out


def test_authors_eight_logit_blocks_are_identical(tmp_path):
    dta, blocks = _real_blocks()
    if dta is None:
        pytest.skip("authors' files not in OSE_CACHE")
    assert len(blocks) == 8
    import shutil
    shutil.copyfile(dta, tmp_path / "d.dta")
    for cmd, expected in blocks:
        it, out = run(f"use d, clear\n{cmd}\n", tmp_path, linesize=99)
        lines = out.splitlines()
        k = next(i for i, ln in enumerate(lines) if ln.startswith(". logit"))
        got = []
        for ln in lines[k + 1:]:
            if ln.startswith(". "):
                break
            got.append(ln)
        while got and got[-1] == "":
            got.pop()
        assert got == expected, cmd


def test_cached_inputs_are_checked_against_the_case_pins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"one")
    import hashlib
    pin = hashlib.sha256(b"one").hexdigest()
    assert _verified([(str(a), pin), (str(b), pin)]) is None          # absent input: offline skip
    b.write_bytes(b"substituted")
    with pytest.raises(AssertionError, match="does not match the case pin"):
        _verified([(str(a), pin), (str(b), pin)])
    b.write_bytes(b"one")
    assert _verified([(str(a), pin), (str(b), pin)]) == [str(a), str(b)]
    # A corrupt file must fail even when its partner is absent: every present input is checked before the skip.
    c = tmp_path / "c"
    b.write_bytes(b"substituted")
    for pins in ([(str(c), pin), (str(b), pin)], [(str(b), pin), (str(c), pin)]):
        with pytest.raises(AssertionError, match="does not match the case pin"):
            _verified(pins)
    assert [p.split(os.sep)[-1] for p, _ in _pins()] == ["7240173.orig", "7240176"]
