"""tabulate (one-way and two-way).

Layout rules below were read off authors' logs on the open list (one-way: five HNPXO1 tables, numeric and
labelled, one with `if`; two-way: 3EDO2Y plain, `row chi2` and `chi2`; 27102 `chi2`, `mi` and 3-column tables) and
are pinned by tests/unit/test_tab.py, on data of ours.
Anything those logs do not show raises Unsupported instead of being guessed. Not yet seen in any open-list log,
so refused: `col` and `cell` (and their key-box lines), two-way `sort`/`generate`, any two-way count of 1,000 or
more (thousands separator), a two-way table wider than 86 columns (panel split), column variables with value
labels, a two-way row label of 3+ lines or with spaces that wraps, one-way string variables (the one logged table
has a 39-column stub the rows shown do not explain), non-integer values, stub wider than 32, a value-label table
with a text longer than every value shown, tied frequencies under `sort`, headers over 3 lines, a long word after
other words in a label, matcell/matrow (no matrices yet), weights, tab1/tab2/tabi/tabm and every other option.
The variable label of `generate()` dummies (`year==1998`) is not pinned by any log yet; it is kept from the
documented behaviour and should be checked when a `describe` log shows it.
"""
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from .. import missing as M
from ..dataset import Variable
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import opt_lookup, parse_standard
from .data import plural, row_mask

MIN_STUB = 11        # stub column is never narrower (HNPXO1 logs, short and 12-character names)
MAX_STUB = 32        # widest stub seen for a numeric variable is 15; wider is not in any log
MAX_HEADER_LINES = 3  # the longest wrapped header in the logs is 3 lines
FREQ_W, PCT_W = 11, 12


def dispw(s):
    """Display columns of s: East Asian wide and fullwidth characters take two."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def wrap_header(text, w):
    """Greedy word wrap at w columns; a word longer than w is cut into w-wide pieces.

    Seen in HNPXO1 logs: a multi-word variable label at 15 breaks at spaces; a single long word (a label
    with no spaces, or a 12-character name) at 11 is hard-cut.
    A long word after other words on the same label is not in any log.
    """
    words = text.split()
    if not words:
        return [""]
    if any(dispw(x) > w for x in words) and len(words) > 1:
        raise Unsupported("tabulate: a long unbroken word inside a longer variable label (layout not yet seen in a log)")
    lines, cur = [], ""
    for word in words:
        while dispw(word) > w:  # only reached when it is the sole word
            piece = ""
            for ch in word:
                if dispw(piece + ch) > w:
                    break
                piece += ch
            lines.append(piece)
            word = word[len(piece):]
        if not cur:
            cur = word
        elif dispw(cur) + 1 + dispw(word) <= w:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def pct2(x):
    """Two-decimal percent with exact ties rounded up: the logs round an exact tie up, so 1/32 prints as 3.13 where '%.2f' gives 3.12."""
    return str(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rjust(s, w):
    return " " * max(w - dispw(s), 0) + s


def value_text(x, tbl, nolabel):
    if x >= M.SYSMISS:
        return M.missing_label(x)
    if not nolabel and tbl is not None:
        k = int(x) if float(x).is_integer() else None
        if k is not None and k in tbl:
            return tbl[k]
    return str(int(x))


def oneway(x, mask, var, ds, *, missing=False, nolabel=False, sort=False):
    """Return (values, counts, texts, stub_width) for a numeric variable on the selected rows."""
    d = x[mask]
    if not missing:
        d = d[d < M.SYSMISS]
    if d.size == 0:
        raise StataError("no observations", 2000)
    vals, counts = np.unique(d, return_counts=True)
    num = vals[vals < M.SYSMISS]
    if np.any(num != np.floor(num)):
        raise Unsupported("tabulate: non-integer values (value text layout not yet seen in a log)")
    tbl = ds.value_labels.get(var.vlabel) if var.vlabel else None
    texts = [value_text(v, tbl, nolabel) for v in vals]
    if sort:
        if len(set(counts.tolist())) != len(counts):
            raise Unsupported("tabulate, sort: tied frequencies (tie order not yet seen in a log)")
        order = np.argsort(-counts, kind="stable")
        vals, counts = vals[order], counts[order]
        texts = [texts[i] for i in order]
    w = max([MIN_STUB] + [dispw(t) for t in texts])
    if tbl and not nolabel:
        # Is the stub sized from the values shown or from every label defined? No log tells; refuse if they differ.
        wall = max([MIN_STUB] + [dispw(t) for t in tbl.values()])
        if wall != w:
            raise Unsupported("tabulate: value label table has a longer text than any value shown "
                              "(stub width rule not yet seen in a log)")
    if w > MAX_STUB:
        raise Unsupported("tabulate: stub column wider than 32 (layout not yet seen in a log)")
    return vals, counts, texts, w


@command("tabulate", 2)
def cmd_tabulate(it, rest):
    p = parse_standard(rest, using=False)
    if p.weight:
        raise Unsupported("tabulate with weights")
    names = p.varlist.split()
    if not names:
        raise StataError("varlist required", 100)
    names = it.ds.expand_varlist(names)
    if len(names) > 2:
        raise StataError("too many variables specified", 103)
    try:
        o = opt_lookup(p.options, "Missing NOLabel Sort GENerate() ROW COLumn CELL CHI2")
    except StataError as e:
        raise Unsupported(f"tabulate option ({e.msg})")
    for k in ("col", "column", "cell"):
        if k in o:
            raise Unsupported(f"tabulate, {k} (layout not yet seen in an open-list log)")
    if len(names) == 2:
        return twoway_cmd(it, p, o, names)
    if "row" in o or "chi2" in o:
        raise Unsupported("tabulate varname, row/chi2 (not allowed with one variable)")
    var = it.ds.find(names[0])
    if var.isstr:
        # The only string tab in the logs has a 39-column stub that the 10 rows shown do not explain.
        raise Unsupported("tabulate of a string variable (stub width rule not yet seen in a log)")
    mask = row_mask(it, p)
    miss, nolab, srt = "missing" in o, "nolabel" in o, "sort" in o
    stub = o.get("generate")
    if "generate" in o and (stub is True or not str(stub).strip()):
        raise StataError("option generate() requires a stub", 198)
    vals, counts, texts, w = oneway(var.data, mask, var, it.ds, missing=miss, nolabel=nolab, sort=srt)
    n = int(counts.sum())
    if stub:
        stub = stub.strip()
        for k in range(1, len(vals) + 1):
            if it.ds.has(f"{stub}{k}"):
                raise StataError(f"variable {stub}{k} already defined", 110)
    # --- print ---
    head = wrap_header(var.label or var.name, w)
    if len(head) > MAX_HEADER_LINES:
        raise Unsupported("tabulate: variable label wraps to more than 3 lines (layout not yet seen in a log)")
    it.print("")
    for ln in head[:-1]:
        it.print(f"{rjust(ln, w)} |")
    it.print(f"{rjust(head[-1], w)} |{'Freq.':>{FREQ_W}}{'Percent':>{PCT_W}}{'Cum.':>{PCT_W}}")
    rule = "-" * (w + 1) + "+" + "-" * (FREQ_W + 2 * PCT_W)
    it.print(rule)
    cum = 0
    for t, c in zip(texts, counts):
        cum += int(c)
        it.print(f"{rjust(t, w)} |{int(c):>{FREQ_W},}{pct2(100.0 * int(c) / n):>{PCT_W}}{pct2(100.0 * cum / n):>{PCT_W}}")
    it.print(rule)
    it.print(f"{rjust('Total', w)} |{n:>{FREQ_W},}{100.0:>{PCT_W}.2f}")
    it.r = {"N": float(n), "r": float(len(vals))}
    if stub:
        allv = var.data
        take = mask & ((allv < M.SYSMISS) | miss)
        order = np.argsort(vals)  # dummies follow value order, not display order
        for k, i in enumerate(order, start=1):
            col = np.where(take, (allv == vals[i]).astype(np.float64), M.SYSMISS)
            lab = f"{var.name}=={texts[i]}"
            it.ds.add(Variable(f"{stub}{k}", "byte", col, label=lab))


MIN_STUB2 = 10        # two-way stub never narrower (the logs pad a short row-variable name to 10)
CELL_W = 10           # every count/percent cell, and the Total column, is 10 wide
MAX_WIDTH2 = 86       # widest two-way table in the logs; panel splitting is in no log
KEY_ROW = ("+----------------+", "| Key            |", "|----------------|",
           "|   frequency    |", "| row percentage |", "+----------------+")


def codes(x, mask, missing):
    """Categories of x on the selected rows: (display values sorted, per-row category index or -1)."""
    if x.dtype == object:
        keep = mask & ((x != "") | missing)
        cats = sorted(set(x[keep].tolist()))
        return cats, np.array([cats.index(v) if k else -1 for v, k in zip(x.tolist(), keep.tolist())])
    keep = mask & ((x < M.SYSMISS) | missing)
    cats = np.unique(x[keep])
    if np.any((cats < M.SYSMISS) & (cats != np.floor(cats))):
        raise Unsupported("tabulate: non-integer values (value text layout not yet seen in a log)")
    idx = np.full(x.shape, -1)
    idx[keep] = np.searchsorted(cats, x[keep])
    return cats.tolist(), idx


def twoway_cmd(it, p, o, names):
    for k in ("sort", "generate"):
        if k in o:
            raise Unsupported(f"tabulate varname1 varname2, {k} (layout not yet seen in a log)")
    rv, cv = it.ds.find(names[0]), it.ds.find(names[1])
    mask = row_mask(it, p)
    miss, nolab, row, chi2 = "missing" in o, "nolabel" in o, "row" in o, "chi2" in o
    rcats, ri = codes(rv.data, mask, miss)
    ccats, ci = codes(cv.data, mask, miss)
    use = (ri >= 0) & (ci >= 0)
    n = int(use.sum())
    if n == 0:
        raise StataError("no observations", 2000)
    # Categories with no observation in the table disappear (Stata drops them), so recount from the used rows.
    rkeep, ckeep = sorted(set(ri[use].tolist())), sorted(set(ci[use].tolist()))
    rmap, cmap = {k: i for i, k in enumerate(rkeep)}, {k: i for i, k in enumerate(ckeep)}
    cnt = np.zeros((len(rkeep), len(ckeep)), dtype=np.int64)
    for a, b in zip(ri[use].tolist(), ci[use].tolist()):
        cnt[rmap[a], cmap[b]] += 1
    nr, nc = cnt.shape
    # --- text of categories ---
    def texts(var, cats, keep, is_col):
        if var.isstr:
            t = [cats[k] for k in keep]
            if any(dispw(x) > MIN_STUB2 for x in t):
                raise Unsupported("tabulate of a string variable wider than 10 (stub width rule not yet seen in a log)")
            return t
        tbl = it.ds.value_labels.get(var.vlabel) if var.vlabel else None
        if is_col and tbl and not nolab:
            raise Unsupported("tabulate: column variable with value labels (header layout not yet seen in a log)")
        t = [value_text(cats[k], tbl, nolab) for k in keep]
        if is_col and any(dispw(x) > CELL_W for x in t):
            raise Unsupported("tabulate: column value wider than 10 (layout not yet seen in a log)")
        if not is_col and tbl and not nolab:
            wall = max([MIN_STUB2] + [dispw(x) for x in tbl.values()])
            if wall != max([MIN_STUB2] + [dispw(x) for x in t]):
                raise Unsupported("tabulate: value label table has a longer text than any value shown "
                                  "(stub width rule not yet seen in a log)")
        return t
    rt, ct = texts(rv, rcats, rkeep, False), texts(cv, ccats, ckeep, True)
    w = max([MIN_STUB2, dispw("Total")] + [dispw(x) for x in rt])
    if w > MAX_STUB:
        raise Unsupported("tabulate: stub column wider than 32 (layout not yet seen in a log)")
    bw = CELL_W + (CELL_W + 1) * (nc - 1)  # width of the column block
    if w + 2 + bw + 2 + CELL_W > MAX_WIDTH2:
        raise Unsupported("tabulate: table wider than any in a log (panel split not yet seen)")
    if cnt.max() >= 1000 or n >= 1000:
        raise Unsupported("tabulate: a two-way count of 1,000 or more (thousands separator not yet seen in a log)")
    if chi2 and (nr < 2 or nc < 2):
        raise Unsupported("tabulate, chi2: table with a single row or column (output not yet seen in a log)")
    rlab, clab = rv.label or rv.name, cv.label or cv.name
    pieces = wrap_header(rlab, w)
    if len(pieces) > 2 or (len(pieces) > 1 and " " in rlab):
        raise Unsupported("tabulate: row variable label that wraps (layout not yet seen in a log beyond a cut name)")
    if dispw(clab) > bw:
        raise Unsupported("tabulate: column variable label wider than the column block (layout not yet seen in a log)")
    # --- print ---
    it.print("")
    if row:
        for ln in KEY_ROW:
            it.print(ln)
        it.print("")
    first, second = ("", pieces[0]) if len(pieces) == 1 else (pieces[0], pieces[1])
    it.print(f"{rjust(first, w)} |{' ' * ((bw - dispw(clab)) // 2 + 1)}{clab}")

    def cells(vals):
        return "".join(f"{rjust(v, CELL_W)}" if i == 0 else f" {rjust(v, CELL_W)}" for i, v in enumerate(vals))
    it.print(f"{rjust(second, w)} |{cells(ct)} |{rjust('Total', CELL_W)}")
    rule = "-" * (w + 1) + "+" + "-" * (bw + 1) + "+" + "-" * CELL_W
    it.print(rule)
    rtot, ctot = cnt.sum(axis=1), cnt.sum(axis=0)

    def line(label, counts, tot, pct_den):
        it.print(f"{rjust(label, w)} |{cells([str(int(c)) for c in counts])} |{rjust(str(int(tot)), CELL_W)} ")
        if row:
            pc = [pct2(100.0 * int(c) / pct_den) for c in counts]
            it.print(f"{' ' * w} |{cells(pc)} |{rjust('100.00', CELL_W)} ")
    for i in range(nr):
        line(rt[i], cnt[i], rtot[i], int(rtot[i]))
        if row or i == nr - 1:
            it.print(rule)
    line("Total", ctot, n, n)
    it.print("")
    it.r = {"N": float(n), "r": float(nr), "c": float(nc)}
    if chi2:
        exp = np.outer(rtot, ctot) / n
        stat = float(((cnt - exp) ** 2 / exp).sum())
        df = (nr - 1) * (nc - 1)
        if df > 99:
            raise Unsupported("tabulate, chi2: more than 99 degrees of freedom (line layout not yet seen in a log)")
        from scipy import stats as SS
        pv = float(SS.chi2.sf(stat, df))
        # the line is right-aligned on its '=' sign: 10 spaces before a 1-digit df, 9 before a 2-digit df
        it.print(f"{' ' * (11 - len(str(df)))}Pearson chi2({df}) = {stat:8.4f}   Pr = {pv:5.3f}")
        it.r.update({"chi2": stat, "p": pv})


for _name in ("tab1", "tab2", "tabi", "tabm"):
    def _unsup(it, rest, _n=_name):
        raise Unsupported(f"{_n}")
    command(_name, len(_name))(_unsup)
