"""egen: the functions that open-list logs show, and nothing else.

Evidence (authors' logs of packages on corpus/open-list.tsv):
  mean, sd, total/sum, min, max, group, tag, rowtotal   HNPXO1 (06_citydev, 07_govreport, 08_green_patent,
                                                        09_final_data_management, 00_main)
  median, pctile(p()), max/min/total with by(), rowtotal(a- b), group(a b c)   27102 masterlog
Behaviour pinned by those logs and by tests/unit/test_egen.py:
  * mean/min/max/sd/median/pctile of a group with no non-missing value are missing; total/sum gives 0
    (HNPXO1 06_citydev: a mean with by() over groups with no value prints the missing-values count line).
  * group(varlist) numbers the distinct value combinations 1..K in sort order and is stored as float by default
    (09_final_data_management: a later `compress` demotes it from float); an observation with a missing
    value in any listed variable gets missing, and the count line is printed.
  * tag(varlist) [if]: no "missing values generated" line in 06_citydev although an `if` is present, so
    observations outside the sample are 0, not missing.
  * rowtotal treats missing as 0 and has no missing-value message (witnessed in 27102, where the only
    missing-values line near a rowtotal belongs to a later division in a plain `generate`).
Everything else (count, rank, rowmean, rowmax, concat, seq, cut, std, mode, ... and the options `missing`, `label`,
`truncate`, `field`, `track`, `unique`) raises Unsupported until a log shows it. Percentiles use the
`summarize, detail` rule written out in `_percentile`; only integer p() in 1..99 is accepted.
Not pinned by any log yet: the storage type of tag() (byte is used) and which observation of a group tag() marks
(the first in the current order is used).
"""
import re

import numpy as np

from .. import missing as M
from ..dataset import NUMERIC, Variable, fits, is_str, to_float32
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import opt_lookup, parse_standard, split_top
from .data import eval_expr, plural, row_mask, store_values

SUPPORTED = {"mean", "sum", "total", "min", "max", "sd", "median", "pctile", "group", "tag", "rowtotal"}
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
FUNC_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", re.S)


def _codes(arrays, n):
    """Dense group codes 0..K-1 for rows, ordered by the key columns (strings by code point)."""
    codes = np.zeros(n, dtype=np.int64)
    for col in arrays:
        key = col.astype(str) if col.dtype == object else col
        _, inv = np.unique(key, return_inverse=True)
        codes = codes * (int(inv.max()) + 1 if n else 1) + inv
        _, codes = np.unique(codes, return_inverse=True)
    return codes.astype(np.int64)


def _row_groups(it, options):
    """Group code per row from the by prefix or the by() option; one group when neither is given."""
    n = it.ds.N
    by = getattr(it, "by", None)
    if by is not None and "by" in options:
        raise StataError("option by() may not be combined with by prefix", 190)
    if by is not None:
        gid = np.empty(n, dtype=np.int64)
        for k, (s, e) in enumerate(zip(by.starts, by.ends)):
            gid[s:e] = k
        return gid, len(by.starts)
    if "by" in options:
        names = it.ds.expand_varlist(str(options["by"]).split())
        gid = _codes([it.ds.find(v).data for v in names], n)
        return gid, int(gid.max()) + 1 if n else 0
    return np.zeros(n, dtype=np.int64), 1 if n else 0


def _percentile(sorted_x, p):
    """p-th percentile of an ascending array, p an integer 1..99.

    P = n*p/100. When P is a whole number the value is the mean of the P-th and (P+1)-th observation, otherwise
    the ceil(P)-th. Written with integer arithmetic so there is no tie in floating point.
    """
    n = len(sorted_x)
    t = n * p
    if t % 100 == 0:
        i = t // 100
        return (sorted_x[i - 1] + sorted_x[i]) / 2.0
    return sorted_x[t // 100]


def _grouped(vals, sel, gid, k, fn, empty):
    """fn(array of the non-missing selected values of each group) -> one number per group; empty if none."""
    ok = sel & (vals < M.SYSMISS)
    out = np.full(k, empty, dtype=np.float64)
    if not ok.any():
        return out
    idx = np.nonzero(ok)[0]
    order = np.argsort(gid[idx], kind="stable")
    idx = idx[order]
    g = gid[idx]
    cuts = np.nonzero(np.diff(g))[0] + 1
    for seg in np.split(idx, cuts):
        out[gid[seg[0]]] = fn(vals[seg])
    return out


def _sd(x):
    if len(x) < 2:
        return M.SYSMISS
    return float(np.sqrt(np.sum((x - np.sum(x) / len(x)) ** 2) / (len(x) - 1)))


def _numeric_arg(it, text):
    vals = eval_expr(it, text)
    if vals.dtype == object:
        raise StataError("type mismatch", 109)
    return np.asarray(vals, dtype=np.float64)


def _first_in_group(keycols, sel, n):
    """True for the first selected row of each distinct key combination (no missing keys)."""
    ok = sel.copy()
    for col in keycols:
        ok &= (col != "") if col.dtype == object else (col < M.SYSMISS)
    out = np.zeros(n, dtype=bool)
    if not ok.any():
        return out
    idx = np.nonzero(ok)[0]
    codes = _codes([c[idx] for c in keycols], len(idx))
    _, first = np.unique(codes, return_index=True)
    out[idx[first]] = True
    return out


@command("egen", 4)
def cmd_egen(it, rest):
    p = parse_standard(rest, using=False)
    if p.exp is None:
        raise StataError("invalid syntax", 198)
    head = p.varlist.split()
    typ = None
    if len(head) == 2:
        typ, name = head
    elif len(head) == 1:
        name = head[0]
    else:
        raise StataError("invalid syntax", 198)
    if typ and typ not in NUMERIC:
        if is_str(typ) or re.match(r"^str(\d+|L)$", typ):
            raise Unsupported("egen with a string storage type")
        raise StataError(f"{typ} invalid type", 198)
    if not NAME_RE.match(name):
        raise StataError(f"{name} invalid name", 198)
    m = FUNC_RE.match(p.exp.strip())
    if not m:
        raise StataError("invalid syntax", 198)
    fcn, args = m.group(1).lower(), m.group(2).strip()
    if fcn not in SUPPORTED:
        raise Unsupported(f"egen function {fcn}() (no open-list log shows it yet)")
    try:
        opts = opt_lookup(p.options, "By() P()" if fcn == "pctile" else "By()")
    except StataError:
        # missing, label, truncate(), field, unique, ...: legal egen options no log has pinned yet. A 198 here would
        # be swallowed by `capture` and the run would go on without the variable, so stop loudly instead.
        raise Unsupported(f"egen {fcn}() option(s) {', '.join(p.options)}")
    if it.ds.has(name):
        raise StataError(f"variable {name} already defined", 110)

    n = it.ds.N
    sel = row_mask(it, p)
    byprefix = getattr(it, "by", None) is not None
    out = np.full(n, M.SYSMISS)
    default_typ = it.settings.get("type", "float")

    if fcn in ("group", "tag", "rowtotal"):
        if byprefix or "by" in opts:
            raise Unsupported(f"egen {fcn}() with by")
        names = it.ds.expand_varlist(re.sub(r"\s*-\s*", "-", args).split())
        if not names:
            raise StataError("invalid syntax", 198)
        cols = [it.ds.find(v) for v in names]
        if fcn == "rowtotal":
            if any(v.isstr for v in cols):
                raise StataError("type mismatch", 109)
            tot = np.zeros(n)
            for v in cols:
                tot += np.where(v.data < M.SYSMISS, v.data, 0.0)
            out = np.where(sel, tot, M.SYSMISS)
        else:
            keycols = [v.data for v in cols]
            if fcn == "group":
                ok = sel.copy()
                for c in keycols:
                    ok &= (c != "") if c.dtype == object else (c < M.SYSMISS)
                if ok.any():
                    idx = np.nonzero(ok)[0]
                    codes = _codes([c[idx] for c in keycols], len(idx))
                    out[idx] = codes + 1
            else:
                out = np.where(_first_in_group(keycols, sel, n), 1.0, 0.0)
                typ = typ or "byte"
    else:
        if not args:
            raise StataError("invalid syntax", 198)
        vals = _numeric_arg(it, args)
        gid, k = _row_groups(it, opts)
        if fcn in ("mean", "min", "max", "sd", "sum", "total"):
            one = {"mean": lambda x: float(np.sum(x) / len(x)), "min": lambda x: float(np.min(x)),
                   "max": lambda x: float(np.max(x)), "sd": _sd, "sum": lambda x: float(np.sum(x)),
                   "total": lambda x: float(np.sum(x))}[fcn]
            empty = 0.0 if fcn in ("sum", "total") else M.SYSMISS
        else:
            pct = 50
            if fcn == "pctile" and "p" in opts:
                try:
                    pct = float(str(opts["p"]).strip())
                except ValueError:
                    raise StataError("option p() incorrectly specified", 198)
            if pct != int(pct) or not 1 <= pct <= 99:
                raise Unsupported("egen pctile p() other than a whole number 1..99")
            pct = int(pct)
            one = lambda x, q=pct: float(_percentile(np.sort(x), q))  # noqa: E731
            empty = M.SYSMISS
        per = _grouped(vals, sel, gid, k, one, empty)
        out = np.where(sel, per[gid] if n else per, M.SYSMISS)

    typ = typ or default_typ
    out = store_values(typ, out)
    if typ in ("byte", "int", "long") and not fits(out, typ):
        raise Unsupported(f"egen result does not fit storage type {typ}")
    it.ds.add(Variable(name, typ, out))
    nm = int((out >= M.SYSMISS).sum())
    if nm:
        it.print(f"({plural(nm, 'missing value', 'missing values')} generated)")
