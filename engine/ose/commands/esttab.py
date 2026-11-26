"""esttab: stored estimates to a CSV results table (one pinned call shape).

Learned from the authors' published CSV files and logs (HNPXO1 tables 2, 3, 6,
7, 9, 10a-c, 11a-c, 12; docs/estimators/esttab.md). The only call shape built:

    esttab names using FILE.csv, replace mtitle(names) se b(%12.4f)
        star(* 0.1 ** 0.05 *** 0.01) s(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps

Anything else raises Unsupported. The package is a community add-on, not a
vendor command; its source was not read.
"""
import os

import numpy as np
from scipy import stats as SS

from ..errors import Unsupported
from ..interp import command
from ..syntax import parse_standard, unquote
from .core import path_of

STARS = [(0.01, "***"), (0.05, "**"), (0.1, "*")]
STAR_LEGEND = "* p<0.1, ** p<0.05, *** p<0.01"
OPTIONS = {"replace", "mtitle", "se", "b", "star", "s", "compress", "nogaps"}


def _cell(text):
    """One CSV cell the way the table writer quotes it: ="text"."""
    return '="' + text + '"'


def _titles(arg):
    """mtitle() words: bare words or "quoted strings", one per model."""
    out, i, s = [], 0, arg.strip()
    while i < len(s):
        if s[i].isspace():
            i += 1
        elif s[i] == '"':
            j = s.find('"', i + 1)
            if j < 0:
                raise Unsupported("esttab mtitle() with an unclosed quote")
            out.append(s[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(s) and not s[j].isspace():
                j += 1
            out.append(s[i:j])
            i = j
    return out


def _check_options(o):
    for name in o:
        if name not in OPTIONS:
            raise Unsupported(f"esttab option {name}")
    missing = sorted(OPTIONS - set(o))
    if missing:
        raise Unsupported(f"esttab without {', '.join(missing)} (only the full pinned option set is built)")
    for flag in ("replace", "se", "compress", "nogaps"):
        if o[flag] is not True:
            raise Unsupported(f"esttab {flag}() with an argument")
    if " ".join(str(o["b"]).split()) != "%12.4f":
        raise Unsupported(f"esttab b({o['b']}) (only %12.4f is pinned)")
    if " ".join(str(o["star"]).split()) != "* 0.1 ** 0.05 *** 0.01":
        raise Unsupported(f"esttab star({o['star']}) (only * 0.1 ** 0.05 *** 0.01 is pinned)")
    if " ".join(str(o["s"]).split()) != "N r2_a, fmt(%9.0f %9.4f %9.4f)":
        raise Unsupported(f"esttab s({o['s']}) (only N r2_a with fmt(%9.0f %9.4f %9.4f) is pinned)")


def _coef(est, name):
    """(b, se) of one coefficient name; base levels and omitted columns are (0, 0)."""
    cols = est["_colnames"]
    if name not in cols:
        return 0.0, 0.0
    j = cols.index(name)
    return float(est["_b"][j]), float(np.sqrt(est["V"][j, j]))


def _star(b, se, df_r):
    t = b / se
    p = 2 * SS.t.sf(abs(t), df_r)
    for cut, mark in STARS:
        if p < cut:
            return mark
    return ""


def _rows(names, ests):
    """Row names: each model's names in its own order, new names appended, _cons last."""
    rows = []
    for e in ests:
        for n in e["_fullnames"]:
            if n != "_cons" and n not in rows:
                rows.append(n)
    if any("_cons" in e["_fullnames"] for e in ests):
        rows.append("_cons")
    return rows


@command("esttab", 4)
def cmd_esttab(it, rest):
    p = parse_standard(rest, using=True)
    if p.if_ is not None or p.in_ is not None or p.weight or p.exp is not None:
        raise Unsupported("esttab with if, in, weights or =exp")
    if p.using is None:
        raise Unsupported("esttab without using (screen table not pinned)")
    _check_options(p.options)
    names = p.varlist.split()
    if not names:
        raise Unsupported("esttab without model names (all stored estimates)")
    target = unquote(p.using)
    if not target.lower().endswith(".csv"):
        raise Unsupported(f"esttab using {target} (only .csv targets are pinned)")
    ests = []
    for n in names:
        if n not in it.estimates:
            raise Unsupported(f"esttab model {n} (no stored estimate of that name)")
        e = it.estimates[n]
        if e.get("cmd") != "reghdfe" or "_fullnames" not in e:
            raise Unsupported(f"esttab model {n} from {e.get('cmd')} (only reghdfe results are pinned)")
        ests.append(e)
    titles = _titles(str(p.options["mtitle"]))
    if len(titles) != len(names) or any('"' in t for t in titles):
        raise Unsupported("esttab mtitle() other than one plain title per model")

    lines = [[""] + [f"({i})" for i in range(1, len(names) + 1)], [""] + titles]
    for row in _rows(names, ests):
        bs, ses = [row], [""]
        for e in ests:
            if row not in e["_fullnames"]:
                bs.append("")
                ses.append("")
                continue
            b, se = _coef(e, row)
            if se == 0.0:
                if b != 0.0:
                    raise Unsupported(f"esttab coefficient {row} with zero standard error")
                bs.append("0.0000")
                ses.append("(.)")
            else:
                bs.append(f"{b:.4f}{_star(b, se, e['df_r'])}")
                ses.append(f"({se:.4f})")
        lines.append(bs)
        lines.append(ses)
    lines.append(["N"] + [f"{e['N']:.0f}" for e in ests])
    lines.append(["r2_a"] + [f"{e['r2_a']:.4f}" for e in ests])
    lines.append(["Standard errors in parentheses"])
    lines.append([STAR_LEGEND])

    path = path_of(it, p.using)
    if not os.path.isdir(os.path.dirname(path) or "."):
        raise Unsupported(f"esttab target directory missing for {target}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for cells in lines:
            f.write(",".join(_cell(c) for c in cells) + "\n")
    it.print(f"(output written to {target})")
