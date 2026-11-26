"""regress (OLS) with robust or one-way clustered standard errors; testparm and lincom after it.

Every number printed here is recorded in docs/estimators/regress.md with its formula, source and
the independent check. The layout comes from open-list logs (3EDO2Y: 173 `reg ..., vce(robust)`
tables and 14 `testparm`; 9N6PBH: 30 `reg ..., cl(id)` tables, 8 `lincom`, 4 factor `testparm`).
5T2U2K pins the unadjusted layout (12 plain `reg`, Source/SS/df/MS block).
Configurations no open-list log has pinned raise Unsupported:
weights, noconstant, level(), collinear regressors (omission note not seen), more model degrees of
freedom than clusters minus one.
"""
import re

import numpy as np
from scipy import stats as SS

from .. import fvars as FV
from ..errors import StataError, Unsupported
from ..fmt import gnum, lead, strip0
from ..interp import command
from ..syntax import opt_lookup, parse_standard
from ..table import NUMW, coef_line, name_width, print_table, abbrev
from .data import row_mask

LEFT = 48      # header: left block, then an 18-wide label, '=', an 11-wide value (3EDO2Y)


def _hdr(left, label, value):
    return f"{left:<{LEFT}}{label:<18}={value:>11}"


def rmse_text(x):
    """Root MSE as the log prints it: 5 significant digits, no leading zero (.31872, 6.0417)."""
    if not (1e-4 <= abs(x) < 1e5):
        raise Unsupported("regress: Root MSE outside the range seen in a log (format not pinned)")
    return lead(strip0(f"{x:.5g}")) if "." in f"{x:.5g}" else f"{x:.5g}"


def _vce(o):
    """('robust', None) | ('cluster', varname) | (None, None) from robust / cl() / vce()."""
    kinds = []
    if "robust" in o:
        kinds.append(("robust", None))
    if "cluster" in o:
        kinds.append(("cluster", str(o["cluster"]).strip()))
    if "vce" in o:
        v = str(o["vce"]).split()
        if len(v) == 1 and "robust".startswith(v[0]) and len(v[0]) >= 1:
            kinds.append(("robust", None))
        elif len(v) == 2 and "cluster".startswith(v[0]) and len(v[0]) >= 2:
            kinds.append(("cluster", v[1]))
        else:
            raise Unsupported(f"regress, vce({o['vce']}) (only robust and one-way cluster are pinned by a log)")
    clusters = {v for k, v in kinds if k == "cluster"}
    if len(clusters) > 1:
        raise Unsupported("regress with two different cluster variables")
    if clusters:
        return "cluster", clusters.pop()     # `robust cl(id)` is the clustered estimate
    return ("robust", None) if kinds else (None, None)


def cluster_codes(var, rows):
    """Integer group code per estimation-sample row for the cluster variable."""
    x = var.data[rows]
    if var.isstr:
        _, codes = np.unique(np.asarray(x, dtype=object).astype(str), return_inverse=True)
    else:
        _, codes = np.unique(x, return_inverse=True)
    return codes


def ols_robust(y, X):
    """OLS with a constant last; HC1 covariance. Returns b, V, e (residuals)."""
    N, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ (X.T @ y)
    e = y - X @ b
    meat = (X * e[:, None]).T @ (X * e[:, None])
    V = XtX_inv @ meat @ XtX_inv * (N / (N - k))
    return b, V, e


def ols_plain(y, X):
    """OLS with a constant last; conventional covariance s^2 (X'X)^-1. Returns b, V, e."""
    N, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ (X.T @ y)
    e = y - X @ b
    return b, XtX_inv * float(e @ e) / (N - k), e


def _ss(x):
    """SS and MS cells: the 11-wide general format (9 significant digits: 347.291806, .238190444)."""
    if x != 0 and not (1e-4 <= abs(x) < 1e8):
        raise Unsupported("regress: sum of squares outside the range seen in a log (format not pinned)")
    return gnum(x, 11)


def anova(it, N, df_m, df_r, mss, rss, tss, F, pF, r2, r2a, rmse):
    """The unadjusted header (5T2U2K, 12 tables): a 12-wide Source column, SS/df/MS, then a
    16-wide label, '=', a 10-wide value on the right."""
    def right(label, value):
        return f"   {label:<16}={value:>10}"
    rule = "-" * 13 + "+" + "-" * 34
    cell = lambda name, ss, df: f"{name:>12} |{_ss(ss):>12}{df:>10,}{_ss(ss / df):>12}"
    it.print("")
    it.print(f"{'Source':>12} |       SS           df       MS   " + right("Number of obs", f"{N:,}"))
    it.print(rule + right(f"F({df_m}, {df_r})", f"{F:.2f}"))
    it.print(cell("Model", mss, df_m) + right("Prob > F", f"{pF:.4f}"))
    it.print(cell("Residual", rss, df_r) + right("R-squared", f"{r2:.4f}"))
    it.print(rule + right("Adj R-squared", f"{r2a:.4f}"))
    it.print(cell("Total", tss, N - 1) + right("Root MSE", rmse_text(rmse)))
    it.print("")


def ols_cluster(y, X, codes):
    """OLS with a constant last; one-way cluster covariance with the G/(G-1)*(N-1)/(N-k) factor.

    Returns b, V, e, G."""
    N, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ (X.T @ y)
    e = y - X @ b
    G = int(codes.max()) + 1
    U = np.zeros((G, k))
    np.add.at(U, codes, X * e[:, None])       # u_g = sum over the cluster of x_i e_i
    V = XtX_inv @ (U.T @ U) @ XtX_inv * (G / (G - 1)) * ((N - 1) / (N - k))
    return b, V, e, G


@command("regress", 3)
def cmd_regress(it, rest):
    p = parse_standard(rest, using=False)
    if p.weight:
        raise Unsupported("regress with weights")
    try:
        o = opt_lookup(p.options, "Robust VCE() CLuster()")
    except StataError as e:
        raise Unsupported(f"regress option ({e.msg})")
    vce, clvar = _vce(o)
    ds = it.ds
    toks = p.varlist.split()
    if not toks:
        raise StataError("varlist required", 100)
    depvar = ds.find(toks[0]).name
    if ds.var(depvar).isstr:
        raise StataError("type mismatch", 109)
    terms = FV.parse(ds, " ".join(toks[1:]))
    if not terms:
        raise Unsupported("regress with no regressors")
    if clvar is not None:
        clvar = ds.find(clvar).name
    mask = FV.complete_cases(ds, [depvar] + FV.variables(terms) + ([clvar] if clvar else []), row_mask(it, p))
    rows = np.nonzero(mask)[0]
    N = len(rows)
    if N == 0:
        raise StataError("no observations", 2000)
    cols = FV.design(ds, terms, rows)
    y = ds.var(depvar).data[rows].astype(np.float64)
    X = np.column_stack([c.data for c in cols] + [np.ones(N)])
    k = X.shape[1]
    if np.linalg.matrix_rank(X) < k:
        raise Unsupported("regress with collinear regressors (omission note not seen in an open-list log)")
    if N - k <= 0:
        raise StataError("insufficient observations", 2001)
    df_m = k - 1
    if vce == "cluster":
        b, V, e, G = ols_cluster(y, X, cluster_codes(ds.var(clvar), rows))
        if G < 2:
            raise StataError("insufficient observations", 2001)
        df_r = G - 1                         # t and F reference: clusters minus one (9N6PBH)
        if df_m > df_r:
            raise Unsupported("regress, cluster with more regressors than clusters minus one "
                              "(F is not reported; layout not pinned)")
    elif vce == "robust":
        b, V, e = ols_robust(y, X)
        df_r = N - k
    else:
        b, V, e = ols_plain(y, X)
        df_r = N - k
    rss = float(e @ e)
    tss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - rss / tss
    r2a = 1 - (1 - r2) * (N - 1) / (N - k)
    rmse = float(np.sqrt(rss / (N - k)))
    bs = b[:-1]
    F = float(bs @ np.linalg.solve(V[:-1, :-1], bs) / df_m)
    pF = float(SS.f.sf(F, df_m, df_r))
    se = np.sqrt(np.diag(V))
    tcrit = SS.t.ppf(0.975, df_r)

    def row(j):
        t = b[j] / se[j]
        return (b[j], se[j], t, 2 * SS.t.sf(abs(t), df_r), b[j] - tcrit * se[j], b[j] + tcrit * se[j])

    if vce is None:
        anova(it, N, df_m, df_r, tss - rss, rss, tss, F, pF, r2, r2a, rmse)
        print_table(it, depvar, cols, [row(j) for j in range(len(cols))], row(len(cols)), None)
        it.e = {"cmd": "regress", "depvar": depvar, "N": float(N), "r2": r2, "r2_a": r2a, "rmse": rmse,
                "F": F, "df_r": float(df_r), "df_m": float(df_m), "rss": rss, "mss": tss - rss, "vce": "ols",
                "_b": b.copy(), "V": V.copy(), "_colnames": [c.name for c in cols] + ["_cons"], "_cols": cols}
        return
    it.print("")
    it.print(_hdr("Linear regression", "Number of obs", f"{N:,}"))
    it.print(_hdr("", f"F({df_m}, {df_r})", f"{F:.2f}"))
    it.print(_hdr("", "Prob > F", f"{pF:.4f}"))
    it.print(_hdr("", "R-squared", f"{r2:.4f}"))
    it.print(_hdr("", "Root MSE", rmse_text(rmse)))
    it.print("")
    if vce == "cluster":
        # Right-aligned to the table's width (9N6PBH: 82-, 84- and 89-column tables).
        tw = name_width(it, cols, depvar=depvar) + NUMW
        it.print(f"(Std. err. adjusted for {G:,} clusters in {clvar})".rjust(tw))
    print_table(it, depvar, cols, [row(j) for j in range(len(cols))], row(len(cols)), "Robust")

    names = [c.name for c in cols] + ["_cons"]
    it.e = {"cmd": "regress", "depvar": depvar, "N": float(N), "r2": r2, "r2_a": r2a, "rmse": rmse,
            "F": F, "df_r": float(df_r), "df_m": float(df_m), "rss": rss, "mss": tss - rss, "vce": vce,
            "vcetype": "Robust", "_b": b.copy(), "V": V.copy(), "_colnames": names, "_cols": cols}
    if vce == "cluster":
        it.e.update({"N_clust": float(G), "clustvar": clvar})


def _testparm_targets(it, e, rest):
    """Coefficient names testparm constrains, in model order.

    Plain variable names (3EDO2Y) or factor terms `i.a`, `i.a#i.b` (9N6PBH), which select every
    shown (non-base) column of the matching model term."""
    out = []
    for tok in rest.split():
        if not any(ch in tok for ch in ".#"):
            for v in it.ds.expand_varlist([tok]):
                if v not in e["_colnames"]:
                    raise StataError(f"variable {v} not found in the model", 111)  # wording not pinned; stops the run
                out.append(v)
            continue
        if "##" in tok or any(ch in tok for ch in "()[]"):
            raise Unsupported(f"testparm {tok} (layout not seen in a log)")
        want = []
        for part in tok.split("#"):
            m = re.fullmatch(r"i\.(\w+)", part)
            if not m:
                raise Unsupported(f"testparm term {part} (only i.var and i.var#i.var are pinned by a log)")
            want.append(it.ds.find(m.group(1)).name)
        hit = [c.name for c in e.get("_cols", [])
               if [x.var for x in c.term.comps] == want and all(x.factor for x in c.term.comps)]
        if not hit:
            raise Unsupported(f"testparm {tok} matching no model term (message not pinned)")
        out.extend(hit)
    return out


@command("testparm", 5)
def cmd_testparm(it, rest):
    if "," in rest:
        raise Unsupported("testparm with options (layout not seen in an open-list log)")
    e = it.e
    if not e or "_b" not in e:
        raise StataError("last estimates not found", 301)
    if e.get("cmd") != "regress":
        raise Unsupported(f"testparm after {e.get('cmd')} (only after regress is pinned by a log)")
    names = _testparm_targets(it, e, rest)
    idx = [e["_colnames"].index(v) for v in names]
    q = len(idx)
    if q == 0 or q > 9:
        raise Unsupported("testparm with 10 or more constraints (numbering layout not seen in a log)")
    b = e["_b"][idx]
    Vs = e["V"][np.ix_(idx, idx)]
    df_r = int(e["df_r"])
    F = float(b @ np.linalg.solve(Vs, b) / q)
    pF = float(SS.f.sf(F, q, df_r))
    it.print("")
    for i, v in enumerate(names, 1):
        it.print(f" ( {i})  {v} = 0")
    it.print("")
    it.print(f"       F({q:3d},{df_r:6d}) ={F:8.2f}")
    it.print(f"            Prob > F ={pF:10.4f}")
    it.r = {"F": F, "p": pF, "df": float(q), "df_r": float(df_r), "drop": 0.0}


@command("lincom", 3)
def cmd_lincom(it, rest):
    """lincom of coefficient names joined by + and - (9N6PBH: `lincom a-b` after reg, cl()).

    Estimate c'b, standard error sqrt(c'Vc), t on e(df_r). Multipliers, constants, `_b[]`,
    equations and options are refused until a log shows them."""
    e = it.e
    if not e or "_b" not in e:
        raise StataError("last estimates not found", 301)
    if e.get("cmd") != "regress":
        raise Unsupported(f"lincom after {e.get('cmd')} (only after regress is pinned by a log)")
    expr = re.sub(r"/\*.*?\*/", "", rest).strip()
    if "," in expr or not re.fullmatch(r"\w+(\s*[-+]\s*\w+)*", expr):
        raise Unsupported(f"lincom {expr} (only sums and differences of coefficient names are pinned)")
    toks = re.findall(r"([-+]?)\s*(\w+)", expr)
    c = np.zeros(len(e["_colnames"]))
    shown = []
    for sign, name in toks:
        if name not in e["_colnames"]:
            name = it.ds.find(name).name
            if name not in e["_colnames"]:
                raise Unsupported(f"lincom of {name}, not a coefficient (message not pinned)")
        c[e["_colnames"].index(name)] += -1.0 if sign == "-" else 1.0
        shown.append((sign, name))
    est = float(c @ e["_b"])
    se = float(np.sqrt(c @ e["V"] @ c))
    df_r = e["df_r"]
    t = est / se
    p = float(2 * SS.t.sf(abs(t), df_r))
    tc = SS.t.ppf(0.975, df_r)
    lo, hi = est - tc * se, est + tc * se
    text = shown[0][1] + "".join(f" {sg} {nm}" for sg, nm in shown[1:])
    w = 12                                   # the dependent variable is abbreviated, never widened (9N6PBH)
    it.print("")
    it.print(f" ( 1)  {text} = 0")
    it.print("")
    it.print("-" * (w + NUMW))
    it.print(f"{abbrev(e['depvar'], w):>{w}} | Coefficient  Std. err.      t    P>|t|     [95% conf. interval]")
    it.print("-" * (w + 1) + "+" + "-" * (NUMW - 2))
    it.print(coef_line("(1)", False, est, se, t, p, lo, hi, namew=w))
    it.print("-" * (w + NUMW))
    it.r = {"estimate": est, "se": se, "t": t, "p": p, "lb": lo, "ub": hi, "df": float(df_r), "level": 95.0}
