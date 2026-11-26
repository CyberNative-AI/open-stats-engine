"""Estimation commands: reghdfe (linear regression absorbing fixed effects), estimates store.

Every number printed here is recorded in docs/estimators/reghdfe.md with its
formula, source and the independent check. Configurations no published log
has pinned raise Unsupported instead of printing a plausible table.
"""
import numpy as np
from scipy import stats as SS

from .. import fvars as FV
from .. import hdfe as H
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import opt_lookup, parse_standard
from ..table import print_table
from .data import row_mask

COLLINEAR_TOL = 1e-9
LEFT = 50


def _hdr(left, right_label, right_value):
    return f"{left:<{LEFT}}{right_label:<16}={right_value:>11}"


def _cluster_opt(o):
    if "vce" in o:
        parts = str(o["vce"]).split()
        if len(parts) == 2 and "cluster".startswith(parts[0]) and len(parts[0]) >= 2:
            return parts[1]
        raise Unsupported(f"reghdfe vce({o['vce']}) (only one-way clustering is pinned by a log)")
    if "cluster" in o:
        parts = str(o["cluster"]).split()
        if len(parts) != 1:
            raise Unsupported("reghdfe multi-way clustering")
        return parts[0]
    raise Unsupported("reghdfe without clustered standard errors (unadjusted and robust layouts not pinned yet)")


def dof_rule(dof, N, k):
    """(parameters counted in the cluster-robust VCE scaling, residual df for Root MSE and adjusted R2).

    Pinned by HNPXO1 logs (docs/estimators/reghdfe.md, "Degrees of freedom").
    With no FE nested in the cluster variable, the constant is the first FE's
    own (redundant 0) and is not counted again. With one or more nested, the
    first remaining FE gives one level to the constant and the constant is
    counted once. Root MSE and adjusted R2 count the nested FEs' levels.
    """
    df_a = sum(r[2] for r in dof)
    nested = [r for r in dof if r[3] == "*"]
    df_a_nested = sum(r[0] for r in nested)
    return df_a + k + (1 if nested else 0), N - k - df_a - df_a_nested


@command("reghdfe", 7)
def cmd_reghdfe(it, rest):
    p = parse_standard(rest, using=False)
    if p.weight:
        raise Unsupported("reghdfe with weights")
    try:
        o = opt_lookup(p.options, "Absorb() VCE() CLuster() allbaselevels")
    except StataError as e:  # an option we have not built is unsupported, not a user error
        raise Unsupported(f"reghdfe option ({e.msg})")
    if o.get("allbaselevels", True) is not True or "noallbaselevels" in o:
        raise Unsupported("reghdfe allbaselevels requires the bare option")
    show_base = "allbaselevels" in o
    if "absorb" not in o or o["absorb"] is True:
        raise Unsupported("reghdfe without absorb() (noabsorb)")
    absorb_text = str(o["absorb"])
    if any(ch in absorb_text for ch in "#=.(,"):
        raise Unsupported(f"reghdfe absorb({absorb_text}) (only plain variables are supported)")
    ds = it.ds
    absvars = ds.expand_varlist(absorb_text.split())
    if len(absvars) < 2:
        raise Unsupported("reghdfe absorbing one variable (output not pinned by a log yet)")
    clvar = ds.find(_cluster_opt(o)).name
    toks = p.varlist.split()
    if not toks:
        raise StataError("varlist required", 100)
    depvar = ds.find(toks[0]).name
    if ds.var(depvar).isstr:
        raise StataError("type mismatch", 109)
    terms = FV.parse(ds, " ".join(toks[1:]), allow_lone_slope=True)
    if not terms:
        raise Unsupported("reghdfe with no regressors")
    if show_base and any(t.interaction for t in terms):
        raise Unsupported("reghdfe allbaselevels with interactions")

    mask = FV.complete_cases(ds, [depvar] + FV.variables(terms) + absvars + [clvar], row_mask(it, p))
    rows = np.nonzero(mask)[0]
    if len(rows) == 0:
        raise StataError("no observations", 2000)
    fe_raw = [H.codes(ds.var(v).data[rows]) for v in absvars]
    keep = H.drop_singletons(fe_raw)
    dropped = int(len(rows) - keep.sum())
    rows = rows[keep]
    N = len(rows)
    groups = [H.codes(ds.var(v).data[rows]) for v in absvars]
    cl = H.codes(ds.var(clvar).data[rows])
    G = int(cl.max()) + 1

    cols = FV.design(ds, terms, rows)
    y = ds.var(depvar).data[rows].astype(np.float64)
    X = np.column_stack([c.data for c in cols])
    Z, iters = H.Absorber(groups).partial(np.column_stack([y, X]))
    yt, Xt = Z[:, 0], Z[:, 1:]

    if dropped:
        it.print(f"(dropped {dropped} singleton observations)")
    it.print(f"(MWFE estimator converged in {iters} iterations)")

    for j, c in enumerate(cols):
        ss0 = np.sum((X[:, j] - X[:, j].mean()) ** 2)
        if ss0 == 0:
            raise Unsupported(f"regressor {c.name} constant in the sample (message not pinned yet)")
        if np.sum(Xt[:, j] ** 2) / ss0 < COLLINEAR_TOL:
            c.omitted = True
            it.print_wrapped(f"note: {c.note_name()} is probably collinear with the fixed effects "
                             f"(all partialled-out values are close to zero; tol = 1.0e-09)")
    slope_cols = [c for c in cols if c.term.lone_slope]
    if slope_cols:
        # The level-specific slopes sum to x. When x is constant within an
        # absorbed group, that sum is absorbed too. Table 4 drops the last level.
        x = ds.var(slope_cols[0].term.comps[1].var).data[rows]
        for g in groups:
            _, first = np.unique(g, return_index=True)
            if np.array_equal(x, x[first[g]]):
                break
        else:
            raise Unsupported("lone slope interaction whose continuous variable varies within every absorbed effect")
        omitted = slope_cols[-1]
        omitted.omitted = True
        it.print_wrapped(f"note: {omitted.name} omitted because of collinearity")

    keepj = [j for j, c in enumerate(cols) if not c.omitted]
    k = len(keepj)
    if k == 0:
        raise Unsupported("reghdfe with every regressor collinear with the fixed effects")
    Xk = Xt[:, keepj]
    if np.linalg.matrix_rank(Xk) < k:
        raise Unsupported("regressors collinear with each other (omission rule not pinned yet)")

    XtX = Xk.T @ Xk
    b = np.linalg.solve(XtX, Xk.T @ yt)
    e = yt - Xk @ b
    rss = float(e @ e)
    xbar = X[:, keepj].mean(axis=0)
    cons = float(y.mean() - xbar @ b)

    dof = H.absorbed_dof(groups, cl)
    df_a = sum(r[2] for r in dof)
    K_vce, df_res = dof_rule(dof, N, k)
    if N - K_vce <= 0 or df_res <= 0 or G < 2:
        raise StataError("insufficient observations", 2001)

    Xa = np.column_stack([Xk + xbar, np.ones(N)])
    bread = np.linalg.inv(Xa.T @ Xa)
    sc = np.zeros((G, k + 1))
    np.add.at(sc, cl, Xa * e[:, None])
    q = (N - 1) / (N - K_vce) * G / (G - 1)
    V = bread @ (sc.T @ sc) @ bread * q
    se = np.sqrt(np.diag(V))
    bb = np.r_[b, cons]
    df_r = G - 1
    tcrit = SS.t.ppf(0.975, df_r)

    def row(j):
        t = bb[j] / se[j]
        pv = 2 * SS.t.sf(abs(t), df_r)
        return (bb[j], se[j], t, pv, bb[j] - tcrit * se[j], bb[j] + tcrit * se[j])

    F = float(b @ np.linalg.solve(V[:k, :k], b) / k)
    pF = float(SS.f.sf(F, k, df_r))
    tss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - rss / tss
    r2w = 1 - rss / float(yt @ yt)
    rmse = np.sqrt(rss / df_res)
    r2a = 1 - (rss / df_res) / (tss / (N - 1))

    it.print("")
    clab = f"Number of clusters ({clvar})"
    it.print(_hdr("HDFE Linear regression", "Number of obs", f"{N:,}"))
    it.print(_hdr(f"Absorbing {len(absvars)} HDFE groups", f"F({k:4d},{df_r:7d})", f"{F:.2f}"))
    it.print(_hdr("Statistics robust to heteroskedasticity", "Prob > F", f"{pF:.4f}"))
    it.print(_hdr("", "R-squared", f"{r2:.4f}"))
    it.print(_hdr("", "Adj R-squared", f"{r2a:.4f}"))
    it.print(_hdr("", "Within R-sq.", f"{r2w:.4f}"))
    it.print(_hdr(f"{clab:<28} ={G:>11,}", "Root MSE", f"{rmse:.4f}"))
    it.print("")
    it.print(f"(Std. err. adjusted for {G:,} clusters in {clvar})".rjust(78))

    stats_rows = []
    pos = 0
    for c in cols:
        if c.omitted:
            stats_rows.append(None)
        else:
            stats_rows.append(row(pos))
            pos += 1
    shown = cols
    if show_base:
        shown = FV.with_base_levels(ds, terms, rows, cols)
        fitted_stats = dict(zip(cols, stats_rows))
        stats_rows = [fitted_stats.get(c) for c in shown]
    print_table(it, depvar, shown, stats_rows, row(k), "Robust")

    it.print("")
    it.print("Absorbed degrees of freedom:")
    it.print("-" * 53 + "+")
    it.print(" Absorbed FE | Categories  - Redundant  = Num. Coefs |")
    it.print("-" * 13 + "+" + "-" * 39 + "|")
    for v, (n, red, nc, mark) in zip(absvars, dof):
        if len(v) > 12:
            raise Unsupported(f"absorbed variable name {v} longer than 12 characters")
        it.print(f"{v:>12} |{n:>10}{red:>12}{nc:>12}{' ' * 4}{mark or ' '}|")
    it.print("-" * 53 + "+")
    if any(r[3] == "?" for r in dof):
        it.print("? = number of redundant parameters may be higher")
    if any(r[3] == "*" for r in dof):
        it.print("* = FE nested within cluster; treated as redundant for DoF computation")

    names = [c.name for c in cols] + ["_cons"]
    fullnames = FV.full_names(ds, terms, rows) + ["_cons"]
    bfull = np.zeros(len(cols) + 1)
    Vfull = np.zeros((len(cols) + 1,) * 2)
    idx = keepj + [len(cols)]
    bfull[idx] = bb
    Vfull[np.ix_(idx, idx)] = V
    it.e = {"cmd": "reghdfe", "depvar": depvar, "N": float(N), "r2": r2, "r2_a": r2a, "r2_within": r2w,
            "rmse": rmse, "F": F, "df_r": float(df_r), "df_m": float(k), "df_a": float(df_a),
            "N_clust": float(G), "rss": rss, "clustvar": clvar, "absvars": " ".join(absvars),
            "_b": bfull, "V": Vfull, "_colnames": names, "_fullnames": fullnames}
    it.r = {}


@command("estimates", 3)
def cmd_estimates(it, rest):
    w = rest.split(None, 1)
    sub = w[0] if w else ""
    arg = w[1].strip() if len(w) > 1 else ""
    if len(sub) >= 3 and "store".startswith(sub):
        names = arg.split(",")[0].split()
        if len(names) != 1:
            raise StataError("estimates store requires one name", 198)
        if not it.e:
            raise StataError("last estimation results not found, nothing to store", 301)
        it.estimates[names[0]] = dict(it.e)
        return
    raise Unsupported(f"estimates {sub}")
