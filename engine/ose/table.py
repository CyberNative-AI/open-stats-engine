"""The coefficient table estimators print, shared by every estimator.

Layout learned from published logs (HNPXO1, see docs/estimators/reghdfe.md; 3EDO2Y and 27102, see
docs/estimators/regress.md): rows grouped by factor-variable term, the numeric block 66 columns wide.

Name column (438 tables in three open-list logs): 12 wide when every row label fits in 12.
When a row label is longer, the column widens to the longest row label if the session is wide enough
(3EDO2Y at linesize 105: up to 32 with a 98-column table; 27102 at linesize 167), and stays 12 with
labels abbreviated `first10~last` when it is not (HNPXO1 at linesize 80: 15-character names). The
dependent variable never widens the column; it is abbreviated to it (a 25-character name shows in 20).
9N6PBH at linesize 90 adds two points: an 18-wide column (an 84-column table, 6 short of
the line) widens; value labels that would need 24 (a 90-column table) cap the column at linesize-67 = 23
and cut the label to `first20..`. So: widen while the table stays 6 or more
columns inside the line; when it would reach the line, variable names abbreviate in 12 (HNPXO1) and
value labels cut at linesize-67 (9N6PBH); a mix of the two, or a gap of 1-5 columns, is refused.
Interaction rows with value labels print one line per factor, ending `label #|`, with the numbers on
the last factor's line (9N6PBH, two-factor interactions only).
"""
from .errors import Unsupported
from .fmt import gnum

NUMW = 66                 # numeric block after the name column, "|" included
NAMEW = 12
WIDE_MARGIN = 6           # smallest witnessed gap between a widened table and the line width (84 in 90, 9N6PBH)


def _name(s, namew=NAMEW):
    if len(s) > namew:
        raise Unsupported(f"coefficient name {s} longer than {NAMEW} characters (abbreviation not pinned yet)")
    return s


def abbrev(s, w=NAMEW):
    """A variable name in a w-character column: first w-2 characters, '~', last character.

    Pinned by HNPXO1 logs (w=12, three names of 15 to 18 characters) and 3EDO2Y (w=20, a 25-character name).
    With names of ours: lnplantcapacity -> lnplantcap~y; at w=20, respondents_trust_council -> respondents_trust_~l.
    """
    return s if len(s) <= w else s[:w - 2] + "~" + s[-1]


def linesize(it):
    return it.linesize()


DEP_WIDEN_MAX = 13


def name_width(it, cols, extra=(), depvar=None):
    """Width of the name column for these design columns (see the module docstring).

    A 13-character dependent variable widens the column when every row label is shorter (5T2U2K logit,
    width 13 in a 99-column session). Longer dependent variables never widen it (a 28-character one is
    abbreviated to the row width in 5T2U2K; 3EDO2Y)."""
    need = [(len(x), False) for x in extra]
    if depvar is not None and len(depvar) <= DEP_WIDEN_MAX:
        need.append((len(depvar), False))
    for r in display_rows(it, cols, namew=32, check=False):
        if r[0] == "head":
            need.append((len(r[1]), False))
        elif r[0] == "row":
            need.append((len(r[1]) + (1 if r[3] else 0), bool(r[4])))
        elif r[0] == "irow":
            need.extend((len(lab) + 1, True) for lab in r[1])
    longest = max([n for n, _ in need] + [NAMEW])
    if longest <= NAMEW:
        return NAMEW
    ls = linesize(it)
    if longest + NUMW + WIDE_MARGIN <= ls and longest <= 32:
        return longest
    if longest + NUMW >= ls:
        cap = ls - 1 - NUMW
        over = [vl for n, vl in need if n > cap]
        if all(vl for vl in over) and NAMEW < cap <= 32:
            return cap                      # value labels cut with '..' (9N6PBH)
        if not any(vl for vl in over):
            return NAMEW                    # variable names abbreviated with '~' (HNPXO1)
        raise Unsupported("coefficient table with both long variable names and long value labels "
                          "(layout not pinned)")
    raise Unsupported(f"coefficient table {longest + NUMW} columns wide at linesize {ls} "
                      "(widen-or-abbreviate rule not pinned this close to the line width)")


def cut_label(s, width):
    """A value label in `width` characters: first width-2, then '..' (9N6PBH: Federal state and lo..)."""
    return s if len(s) <= width else s[:width - 2] + ".."


def _level_label(it, var, lev, namew=NAMEW, *, base=False):
    """(text, uses value-label width rules) for one factor level."""
    tab = _vlabels(it, var)
    if tab is not None and lev in tab:
        if base:  # HNPXO1 Figure 4 uses the name abbreviation for a long base label.
            return abbrev(tab[lev], namew - 1), False
        return cut_label(tab[lev], namew - 1), True
    s = str(int(lev))
    if len(s) > namew - 1:
        raise Unsupported(f"level {s} longer than {namew - 1} characters (abbreviation not pinned yet)")
    return s, False


def _vlabels(it, var):
    v = it.ds.var(var)
    if v.vlabel and v.vlabel in it.ds.value_labels:
        return it.ds.value_labels[v.vlabel]
    return None


def display_rows(it, cols, namew=NAMEW, check=True):
    """List of ('blank',) | ('head', text[, separator]) |
    ('row', label, index, indent, is_value_label) | ('irow', [label per factor], index).

    check=False returns full (unabbreviated) labels, for measuring the name column."""
    if not check:
        namew = 10 ** 6
    nm = (lambda x: x) if not check else (lambda x: _name(x, namew))
    ab = (lambda x: x) if not check else (lambda x: abbrev(x, namew))
    out = []
    i = 0
    n = len(cols)

    def blank():
        if out and out[-1][0] != "blank":
            out.append(("blank",))

    while i < n:
        t = cols[i].term
        j = i
        while j < n and cols[j].term is t:
            j += 1
        members = list(range(i, j))
        if not t.interaction and not t.comps[0].factor:
            out.append(("row", ab(t.comps[0].var), i, False, False))
        elif not t.interaction:
            var = t.comps[0].var
            if len(members) == 1 and not cols[i].base and _vlabels(it, var) is None:
                out.append(("row", nm(cols[i].name), i, False, False))
            else:
                blank()
                out.append(("head", nm(var)))
                for k in members:
                    lab, vl = _level_label(it, var, cols[k].levels[0], namew, base=cols[k].base)
                    out.append(("row", lab, k, True, vl))
                if len(members) > 1:
                    # A group of 2+ rows is closed by a separator (HNPXO1 a13 ownership with its base row,
                    # 3EDO2Y survey 2/3); a one-row group is not (HNPXO1 a02 ownership: State-owned then _cons).
                    blank()
        else:
            labelled = [c.factor and _vlabels(it, c.var) is not None for c in t.comps]
            if any(labelled) and not (len(t.comps) == 2 and all(labelled)):
                raise Unsupported("interaction rows with value labels other than two labelled factors "
                                  "(layout not pinned yet)")
            blank()
            if t.lone_slope:
                factor, continuous = t.comps
                out.append(("head", nm(factor.var), "#"))
                out.append(("head", nm(f"c.{continuous.var}")))
            else:
                head = "#".join(c.var if c.factor else f"c.{c.var}" for c in t.comps)
                out.append(("head", nm(head)))
            for k in members:
                if any(labelled):
                    out.append(("irow", [_level_label(it, c.var, lv, namew)[0]
                                         for c, lv in zip(t.comps, cols[k].levels)], k))
                    continue
                labs = [str(int(lv)) for c, lv in zip(t.comps, cols[k].levels) if c.factor]
                lab = " ".join(labs)
                if len(lab) > namew - 1:
                    raise Unsupported("interaction level label too long (layout not pinned yet)")
                out.append(("row", lab, k, True, False))
            blank()
        i = j
    return out


def coef_line(label, indent, b, se, t, p, lo, hi, namew=NAMEW):
    lab = (label.rjust(namew - 1) + " ") if indent else label.rjust(namew)
    return (f"{lab} |{gnum(b, 9):>11}{gnum(se, 9):>11}{t:9.2f}{p:8.3f}"
            f"{gnum(lo, 9):>13}{gnum(hi, 9):>12}")


def zero_line(label, indent, namew=NAMEW, status="omitted"):
    lab = (label.rjust(namew - 1) + " ") if indent else label.rjust(namew)
    return f"{lab} |{'0':>11}  ({status})"


def print_table(it, depvar, cols, stats, cons_stats, vce_title, level=95, stat="t"):
    """stats[k] = (b, se, t, p, lo, hi) or None for base and omitted rows.

    stat="z" prints the maximum-likelihood variant: columns `z` and `P>|z|`, and the capital-S
    `Std. err.` title with no VCE row (5T2U2K logit, 22 tables; same widths as the t table)."""
    w = name_width(it, cols, depvar=depvar)
    rule = "-" * (w + NUMW)
    it.print(rule)
    if vce_title:
        it.print(" " * (w + 1) + "|" + " " * 15 + vce_title)
        se_title = "std. err."
    else:
        se_title = "Std. err."       # no title row, capital S (5T2U2K plain regress; lincom in 9N6PBH)
    tt = "      z    P>|z|" if stat == "z" else "      t    P>|t|"
    it.print(f"{abbrev(depvar, w):>{w}} | Coefficient  {se_title}{tt}     [{level}% conf. interval]")
    it.print("-" * (w + 1) + "+" + "-" * (NUMW - 2))
    for r in display_rows(it, cols, namew=w):
        if r[0] == "blank":
            it.print(" " * (w + 1) + "|")
        elif r[0] == "head":
            sep = r[2] if len(r) == 3 else " "
            it.print(f"{r[1]:>{w}}{sep}|")
        elif r[0] == "irow":
            _, labs, k = r
            for lab in labs[:-1]:
                it.print(f"{lab:>{w - 1}} #|")
            if stats[k] is None:
                it.print(zero_line(labs[-1], True, w))
            else:
                it.print(coef_line(labs[-1], True, *stats[k], namew=w))
        else:
            _, label, k, indent, _vl = r
            if cols[k].base:
                it.print(zero_line(label, indent, w, status="base"))
            elif stats[k] is None:
                it.print(zero_line(label, indent, w))
            else:
                it.print(coef_line(label, indent, *stats[k], namew=w))
    if cons_stats is not None:
        it.print(coef_line("_cons", False, *cons_stats, namew=w))
    it.print(rule)
