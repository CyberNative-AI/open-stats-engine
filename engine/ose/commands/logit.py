"""logit: binary logistic regression by maximum likelihood, default (observed information) covariance.

Every number printed here is recorded in docs/estimators/logit.md with its formula, source and the
independent check. The layout and the iteration log come from the authors' logs of open-list package
5T2U2K (Replication.log: 8 `logit` blocks, all replayed; Replication_Appendix.log: 28 more, 20 replayed).
Configurations not built raise Unsupported: robust and clustered covariance (an open-list log shows that
layout; not built yet), weights, offset(), constraints(), or, noconstant, level(), collinear regressors,
perfect prediction, outcomes other than 0 and 1, a log likelihood of 1e5 or more in absolute value.
"""
import numpy as np
from scipy import stats as SS

from .. import fvars as FV
from ..errors import StataError, Unsupported
from ..fmt import gnum
from ..interp import command
from ..syntax import opt_lookup, parse_standard
from ..table import print_table
from .data import row_mask

LEFT = 56          # header: the left block is 56 columns, then the right label, " = ", a 6-wide value
MAXITER = 16000    # Stata's default; the loop stops as "not converged" long before in every case seen
STEP_UP = 0.125   # step rule 2: add this to the step length while the log likelihood still rises
FTOL = 1e-7        # convergence: relative change of the log likelihood between two iterations


def _ll(y, eta):
    """Log likelihood of a logit with linear predictor eta, stable for large |eta|."""
    return float(np.sum(y * eta - np.logaddexp(0.0, eta)))


def newton(X, y, ftol=FTOL, expand=True):
    """Newton-Raphson for the logit likelihood from the constant-only fit (constant is the last column).

    Starting values: slopes 0, constant log(ybar/(1-ybar)); iteration 0 is that log likelihood.
    Direction: d = (X'WX)^-1 X'(y - p) with W = diag(p(1-p)).
    Step rule 2 (the one that reproduces the authors' digits): try s = 1; if the log likelihood falls,
    halve s until it does not; otherwise keep adding 1/8 to s while the log likelihood still rises.
    expand=False is step rule 1 (plain full step, halved on a fall), kept for the record in
    docs/estimators/logit.md: it misses 4 of the 8 authors' iteration logs in 5T2U2K.
    Stops after the first iteration whose log likelihood moved by less than ftol relative to its own size.

    Returns (b, V, lls, converged) with lls[k] the log likelihood at iteration k."""
    N, k = X.shape
    ybar = float(y.mean())
    b = np.zeros(k)
    b[-1] = np.log(ybar / (1.0 - ybar))
    ll = _ll(y, X @ b)
    lls = [ll]
    for _ in range(MAXITER):
        p = 1.0 / (1.0 + np.exp(-(X @ b)))
        w = p * (1.0 - p)
        d = np.linalg.solve((X * w[:, None]).T @ X, X.T @ (y - p))
        s = 1.0
        nll = _ll(y, X @ (b + d))
        if nll < ll:
            while nll < ll and s > 1e-10:
                s /= 2.0
                nll = _ll(y, X @ (b + s * d))
        elif expand:
            while True:
                more = _ll(y, X @ (b + (s + STEP_UP) * d))
                if more <= nll:
                    break
                s += STEP_UP
                nll = more
        change = abs(nll - ll)
        b, ll = b + s * d, nll
        lls.append(ll)
        if change < ftol * abs(ll):
            p = 1.0 / (1.0 + np.exp(-(X @ b)))
            w = p * (1.0 - p)
            V = np.linalg.inv((X * w[:, None]).T @ X)
            return b, V, lls, True
    return b, None, lls, False


def _lltext(x):
    if not (1e-4 <= abs(x) < 1e5):
        raise Unsupported("logit: log likelihood outside the range seen in a log (format not pinned)")
    return gnum(x, 10)


def _hdr(left, label, value):
    return f"{left:<{LEFT}}{label:<13} = {value:>6}"


def _perfect(cols_data, y):
    """True if some regressor column predicts the outcome perfectly: its non-zero cells all share one y."""
    for x in cols_data:
        nz = x != 0
        if nz.any() and (y[nz].min() == y[nz].max()):
            return True
    return False


@command("logit", 5)
def cmd_logit(it, rest):
    p = parse_standard(rest, using=False)
    if p.weight:
        raise Unsupported("logit with weights")
    try:
        o = opt_lookup(p.options, "Robust VCE() CLuster()")
    except StataError as e:
        raise Unsupported(f"logit option ({e.msg})")
    if o:
        raise Unsupported("logit with robust or clustered covariance (not built yet)")
    ds = it.ds
    toks = p.varlist.split()
    if not toks:
        raise StataError("varlist required", 100)
    depvar = ds.find(toks[0]).name
    if ds.var(depvar).isstr:
        raise StataError("type mismatch", 109)
    terms = FV.parse(ds, " ".join(toks[1:]))
    if not terms:
        raise Unsupported("logit with no regressors")
    mask = FV.complete_cases(ds, [depvar] + FV.variables(terms), row_mask(it, p))
    rows = np.nonzero(mask)[0]
    N = len(rows)
    if N == 0:
        raise StataError("no observations", 2000)
    y = ds.var(depvar).data[rows].astype(np.float64)
    if not np.all((y == 0) | (y == 1)):
        raise Unsupported("logit with an outcome other than 0 and 1 (message not pinned)")
    if y.min() == y.max():
        raise StataError("outcome does not vary", 2000)
    cols = FV.design(ds, terms, rows)
    X = np.column_stack([c.data for c in cols] + [np.ones(N)])
    k = X.shape[1]
    if np.linalg.matrix_rank(X) < k:
        raise Unsupported("logit with collinear regressors (omission note not seen in an open-list log)")
    if _perfect([c.data for c in cols], y):
        raise Unsupported("logit with a perfect predictor (note not seen in an open-list log)")
    b, V, lls, conv = newton(X, y)
    if not conv:
        raise Unsupported("logit did not converge (message not pinned)")
    if float(np.max(np.abs(b))) > 20:
        raise Unsupported("logit with an extreme coefficient (possible separation; layout not pinned)")
    ll, ll0 = lls[-1], lls[0]
    df_m = k - 1
    chi2 = 2.0 * (ll - ll0)
    pchi = float(SS.chi2.sf(chi2, df_m))
    r2p = 1.0 - ll / ll0
    se = np.sqrt(np.diag(V))
    zc = SS.norm.ppf(0.975)

    def row(j):
        z = b[j] / se[j]
        return (b[j], se[j], z, 2 * SS.norm.sf(abs(z)), b[j] - zc * se[j], b[j] + zc * se[j])

    it.print("")
    for i, v in enumerate(lls):
        it.print(f"Iteration {i}:   log likelihood = {_lltext(v):>10}  ")
    it.print("")
    it.print(_hdr("Logistic regression", "Number of obs", f"{N:,}"))
    it.print(_hdr("", f"LR chi2({df_m})", f"{chi2:.2f}"))
    it.print(_hdr("", "Prob > chi2", f"{pchi:.4f}"))
    it.print(_hdr(f"Log likelihood = {_lltext(ll)}", "Pseudo R2", f"{r2p:.4f}"))
    it.print("")
    print_table(it, depvar, cols, [row(j) for j in range(len(cols))], row(len(cols)), None, stat="z")

    names = [c.name for c in cols] + ["_cons"]
    it.e = {"cmd": "logit", "depvar": depvar, "N": float(N), "ll": ll, "ll_0": ll0, "r2_p": r2p,
            "chi2": chi2, "p": pchi, "df_m": float(df_m), "rank": float(k), "converged": 1.0,
            "ic": float(len(lls) - 1), "k": float(k), "k_eq": 1.0, "k_dv": 1.0,
            "_b": b.copy(), "V": V.copy(), "_colnames": names, "_cols": cols}
    it.r = {}
