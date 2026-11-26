"""Factor-variable varlists: `i.x`, `c.x`, `ib#.x`, `a#b`, `a##b`.

Shared by every estimator. `parse` turns the varlist text into terms;
`design` turns terms into design columns for a given estimation sample.

What is supported is what published logs have pinned (see
docs/estimators/reghdfe.md, "Coefficient table layout"). Anything else raises
Unsupported rather than printing a guessed table.
"""
import itertools
import re

import numpy as np

from . import missing as M
from .errors import StataError, Unsupported

COMP_RE = re.compile(r"^(?:(i|c|ib(\d+)|ibn)\.)?([A-Za-z_][A-Za-z0-9_]*)$")


class Comp:
    """One variable inside a term."""

    def __init__(self, var, factor, base=None, explicit=False):
        self.var = var
        self.factor = factor
        self.base = base          # None = lowest level
        self.explicit = explicit  # written with c. (shown as c.x inside an interaction)

    def key(self):
        return (self.var, self.factor)


class Term:
    """A main effect (one component) or an interaction (several)."""

    def __init__(self, comps, lone_slope=False):
        self.comps = comps
        self.lone_slope = lone_slope

    @property
    def interaction(self):
        return len(self.comps) > 1

    @property
    def vars(self):
        return [c.var for c in self.comps]


def _comp(ds, text, in_interaction):
    m = COMP_RE.match(text)
    if not m:
        raise Unsupported(f"factor-variable notation {text}")
    pre, base, name = m.group(1), m.group(2), m.group(3)
    var = ds.find(name).name
    if ds.var(var).isstr:
        raise StataError(f"{var}:  string variables may not be used as factor variables" if pre in ("i", "ibn") or (pre is None and in_interaction) else "type mismatch", 109)
    if pre == "ibn":
        raise Unsupported("ibn. (no base level) factor variables")
    if pre == "c":
        return Comp(var, False, explicit=True)
    if pre is None and not in_interaction:
        return Comp(var, False)
    return Comp(var, True, base=float(base) if base is not None else None)


def parse(ds, text, *, allow_lone_slope=False):
    """Parse a factor-variable varlist into a list of Terms (order kept, duplicates dropped)."""
    terms = []
    seen = set()

    def add(comps, lone_slope=False):
        k = tuple(sorted(c.key() for c in comps))
        if lone_slope and k in seen:
            raise Unsupported("lone slope interaction repeats an existing term")
        if k not in seen:
            seen.add(k)
            terms.append(Term(comps, lone_slope))

    for tok in text.split():
        if "(" in tok or ")" in tok:
            raise Unsupported(f"factor-variable grouping {tok}")
        if "##" in tok:
            parts = [_comp(ds, p, True) for p in tok.split("##")]
            for r in range(1, len(parts) + 1):
                for combo in itertools.combinations(parts, r):
                    add(list(combo))
        elif "#" in tok:
            parts = tok.split("#")
            if not allow_lone_slope or sorted(p[:2] for p in parts) != ["c.", "i."]:
                raise Unsupported(f"interaction {tok} without ## (main effects)")
            add([_comp(ds, p, True) for p in parts], lone_slope=True)
        elif "." in tok:
            add([_comp(ds, tok, False)])
        else:
            for name in ds.expand_varlist([tok]):
                if ds.var(name).isstr:
                    raise StataError("string variables not allowed in varlist;\n" + name + " is a string variable", 109)
                add([Comp(name, False)])
    slopes = [t for t in terms if t.lone_slope]
    if slopes:
        slope = slopes[0]
        if len(slopes) > 1 or any(set(slope.vars).intersection(t.vars) for t in terms if t is not slope):
            raise Unsupported("lone slope interaction with related terms or multiple lone slopes")
    return terms


def variables(terms):
    out = []
    for t in terms:
        for v in t.vars:
            if v not in out:
                out.append(v)
    return out


class Column:
    """One design column and how the coefficient table shows it."""

    def __init__(self, name, data, term, levels, *, base=False):
        self.name = name        # e.g. "1.zone", "1.zone#1.after", "span", "1.after#c.span"
        self.data = data
        self.term = term
        self.levels = levels    # level per factor component (None for continuous)
        self.base = base        # table-only column, without data
        self.omitted = False

    def note_name(self):
        """Name used in the 'probably collinear' note (base-free form, e.g. 1bn.after)."""
        if self.term.interaction:
            raise Unsupported("collinearity note for an interaction term")
        c = self.term.comps[0]
        if c.factor:
            return f"{_lev(self.levels[0])}bn.{c.var}"
        raise Unsupported("collinearity note for a continuous variable")


def _lev(v):
    return str(int(v))


def _levels_of(ds, terms, rows):
    """{var: (sorted levels in the sample, base level)} for every factor component."""
    levels_of = {}
    for t in terms:
        for c in t.comps:
            if c.factor and c.var not in levels_of:
                x = ds.var(c.var).data[rows]
                if np.any(x < 0) or np.any(x != np.floor(x)):
                    raise Unsupported(f"factor variable {c.var} with negative or non-integer values")
                lv = np.unique(x)
                base = lv[0] if c.base is None else c.base
                if base not in lv:
                    raise Unsupported(f"base level {c.base} not in the sample for {c.var}")
                levels_of[c.var] = (lv, base)
    return levels_of


def full_names(ds, terms, rows):
    """Coefficient names for every level combination, base levels included, in varlist order.

    The estimates table writers show the base level of a factor as a row of its
    own (`0.zone`, `1.tier`) next to the estimated levels. Same naming as `design`.
    """
    levels_of = _levels_of(ds, terms, rows)
    out = []
    for t in terms:
        comps = [c for c in t.comps if c.factor] + [c for c in t.comps if not c.factor]
        choices = [list(levels_of[c.var][0]) if c.factor else [None] for c in comps]
        for combo in itertools.product(*choices):
            parts = []
            for c, lev in zip(comps, combo):
                if c.factor:
                    parts.append(f"{_lev(lev)}.{c.var}")
                else:
                    parts.append(f"c.{c.var}" if t.interaction else c.var)
            out.append("#".join(parts))
    return out


def design(ds, terms, rows):
    """Build design columns over the given row indices (the estimation sample)."""
    cols = []
    levels_of = _levels_of(ds, terms, rows)
    for t in terms:
        # Display order inside an interaction: factor components first, then continuous.
        comps = [c for c in t.comps if c.factor] + [c for c in t.comps if not c.factor]
        t.comps = comps
        if t.interaction and sum(1 for c in comps if not c.factor) > 1:
            raise Unsupported("interaction of two continuous variables")
        choices = []
        for c in comps:
            if c.factor:
                lv, base = levels_of[c.var]
                choices.append(lv if t.lone_slope else [v for v in lv if v != base])
            else:
                choices.append([None])
        for combo in itertools.product(*choices):
            data = np.ones(len(rows))
            parts = []
            for c, lev in zip(comps, combo):
                x = ds.var(c.var).data[rows]
                if c.factor:
                    data = data * (x == lev)
                    parts.append(f"{_lev(lev)}.{c.var}")
                else:
                    data = data * x
                    parts.append(f"c.{c.var}" if t.interaction else c.var)
            if t.interaction and not np.any(data):
                raise Unsupported(f"empty interaction cell {'#'.join(parts)}")
            cols.append(Column("#".join(parts), data.astype(np.float64), t, list(combo)))
    return cols


def with_base_levels(ds, terms, rows, cols):
    """Insert base rows for single-factor terms without adding to the fitted design."""
    levels_of = _levels_of(ds, terms, rows)
    by_term = {t: [] for t in terms}
    for c in cols:
        by_term[c.term].append(c)
    shown = []
    for t, members in by_term.items():
        comp = t.comps[0]
        if not t.interaction and comp.factor:
            levels, base = levels_of[comp.var]
            pos = int(np.searchsorted(levels, base))
            members.insert(pos, Column(f"{_lev(base)}.{comp.var}", None, t, [base], base=True))
        shown.extend(members)
    return shown


def complete_cases(ds, varnames, mask):
    """Mark out observations with a missing value in any of the variables."""
    m = mask.copy()
    for v in varnames:
        var = ds.var(v)
        if var.isstr:
            m &= np.array([s != "" for s in var.data], dtype=bool)
        else:
            m &= var.data < M.SYSMISS
    return m
