"""summarize."""
import numpy as np

from .. import missing as M
from ..errors import StataError, Unsupported
from ..fmt import gnum
from ..interp import command
from ..syntax import opt_lookup, parse_standard
from .data import row_mask


TITLE_WRAP = 49


def g9(x):
    return gnum(x, 9)


def pctile(xs, p):
    """Percentile as summarize reports it (unweighted).

    With n sorted values and P = n*p/100: if P is a whole number the result
    is the mean of the P-th and (P+1)-th values, otherwise the ceil(P)-th.
    """
    n = len(xs)
    P = n * p / 100.0
    i = int(np.floor(P))
    if abs(P - round(P)) < 1e-12 and 1 <= round(P) < n:
        i = int(round(P))
        return (xs[i - 1] + xs[i]) / 2.0
    k = int(np.ceil(P))
    k = min(max(k, 1), n)
    return xs[k - 1]


def moments(x):
    n = len(x)
    mean = float(np.mean(x)) if n else M.SYSMISS
    if n > 1:
        d = x - mean
        var = float(np.sum(d * d) / (n - 1))
    else:
        var = M.SYSMISS if n == 0 else 0.0
    return n, mean, var


def center(s, w):
    pad = w - len(s)
    if pad <= 0:
        return s
    return " " * (pad // 2) + s


def wrap_title(s, w):
    if len(s) <= w:
        return [s]
    out = []
    while len(s) > w:
        k = s.rfind(" ", 0, w + 1)
        if k <= 0:
            k = w
        out.append(s[:k].rstrip())
        s = s[k:].lstrip()
    if s:
        out.append(s)
    return out


@command("summarize", 2)
def cmd_summarize(it, rest):
    p = parse_standard(rest, using=False)
    o = opt_lookup(p.options, "Detail MEANonly Format SEParator()")
    if p.weight:
        raise Unsupported("summarize with weights")
    names = it.ds.expand_varlist(p.varlist.split()) if p.varlist.strip() else it.ds.names()
    mask = row_mask(it, p)
    if "detail" in o:
        for n in names:
            _detail(it, n, mask)
        return
    rows = []
    for n in names:
        v = it.ds.find(n)
        if v.isstr:
            rows.append((n, 0, None, None, None, None))
            it.r = {"N": 0.0, "sum_w": 0.0, "sum": 0.0}
            continue
        x = v.data[mask]
        x = x[x < M.SYSMISS]
        k, mean, var = moments(x)
        mn = float(x.min()) if k else M.SYSMISS
        mx = float(x.max()) if k else M.SYSMISS
        rows.append((n, k, mean, var, mn, mx))
        it.r = {"N": float(k), "sum_w": float(k), "mean": mean, "Var": var,
                "sd": float(np.sqrt(var)) if k > 1 else M.SYSMISS, "min": mn, "max": mx,
                "sum": float(np.sum(x)) if k else 0.0}
        if k == 0:
            for key in ("mean", "Var", "sd", "min", "max"):
                it.r.pop(key, None)
    if "meanonly" in o:
        return
    it.print("")
    it.print("    Variable |        Obs        Mean    Std. dev.       Min        Max")
    it.print("-------------+---------------------------------------------------------")
    for n, k, mean, var, mn, mx in rows:
        nm = n if len(n) <= 12 else n[:5] + "~" + n[-6:]
        if not k:
            it.print(f"{nm:>12} |{k:>11,}")
            continue
        sd = np.sqrt(var) if k > 1 else M.SYSMISS
        sds = g9(sd) if k > 1 else "."
        it.print(f"{nm:>12} |{k:>11,}{g9(mean):>12}{sds:>12}{g9(mn):>11}{g9(mx):>11}")


def _detail(it, name, mask):
    v = it.ds.find(name)
    if v.isstr:
        raise Unsupported("summarize, detail on a string variable")
    x = np.sort(v.data[mask][v.data[mask] < M.SYSMISS])
    n, mean, var = moments(x)
    title = v.label or name
    it.print("")
    # Long titles wrap; one published log pins the width to 46..50 columns.
    for t in wrap_title(title, TITLE_WRAP):
        it.print(center(t, 61))
    it.print("-" * 61)
    if n == 0:
        it.print("no observations")
        return
    sd = float(np.sqrt(var))
    d = x - mean
    m2 = float(np.mean(d ** 2))
    skew = float(np.mean(d ** 3) / m2 ** 1.5) if m2 > 0 else M.SYSMISS
    kurt = float(np.mean(d ** 4) / m2 ** 2) if m2 > 0 else M.SYSMISS
    ps = {q: pctile(x, q) for q in (1, 5, 10, 25, 50, 75, 90, 95, 99)}
    small = list(x[:4]) + [None] * (4 - min(4, n))
    large = list(x[-4:]) if n >= 4 else list(x) + [None] * (4 - n)
    f = lambda z: g9(z) if z is not None else ""
    W = lambda s, w: f"{s:>{w}}"
    it.print("      Percentiles      Smallest")
    it.print(f" 1%{W(f(ps[1]), 13)}{W(f(small[0]), 15)}")
    it.print(f" 5%{W(f(ps[5]), 13)}{W(f(small[1]), 15)}")
    it.print(f"10%{W(f(ps[10]), 13)}{W(f(small[2]), 15)}       Obs         {W(f'{n:,}', 11)}")
    it.print(f"25%{W(f(ps[25]), 13)}{W(f(small[3]), 15)}       Sum of wgt. {W(f'{n:,}', 11)}")
    it.print("")
    it.print(f"50%{W(f(ps[50]), 13)}{'':15}       Mean        {W(g9(mean), 11)}")
    it.print(f"{'':24}Largest       Std. dev.   {W(g9(sd) if n > 1 else '.', 11)}")
    lg = large[-4:] if n >= 4 else large
    it.print(f"75%{W(f(ps[75]), 13)}{W(f(lg[0]), 15)}")
    it.print(f"90%{W(f(ps[90]), 13)}{W(f(lg[1]), 15)}       Variance    {W(g9(var) if n > 1 else '.', 11)}")
    it.print(f"95%{W(f(ps[95]), 13)}{W(f(lg[2]), 15)}       Skewness    {W(g9(skew), 11)}")
    it.print(f"99%{W(f(ps[99]), 13)}{W(f(lg[3]), 15)}       Kurtosis    {W(g9(kurt), 11)}")
    it.r = {"N": float(n), "sum_w": float(n), "mean": mean, "Var": var, "sd": sd, "skewness": skew,
            "kurtosis": kurt, "sum": float(np.sum(x)), "min": float(x[0]), "max": float(x[-1])}
    for q in ps:
        it.r[f"p{q}"] = float(ps[q])
