"""The in-memory dataset: one rectangular table of typed columns."""
import fnmatch

import numpy as np

from . import missing as M
from .errors import StataError

NUMERIC = ("byte", "int", "long", "float", "double")
DEFAULT_FMT = {"byte": "%8.0g", "int": "%8.0g", "long": "%12.0g", "float": "%9.0g", "double": "%10.0g"}
RANGE = {"byte": (-127, 100), "int": (-32767, 32740), "long": (-2147483647, 2147483620)}


def is_str(t):
    return t.startswith("str")


def default_format(t):
    if is_str(t):
        return "%9s" if t == "strL" else f"%{max(int(t[3:]), 1)}s"
    return DEFAULT_FMT[t]


def to_float32(a):
    """Round values to float storage precision, keeping missing codes."""
    a = np.asarray(a, dtype=np.float64)
    miss = a >= M.SYSMISS
    with np.errstate(over="ignore"):
        out = a.astype(np.float32).astype(np.float64)
    if miss.any():
        out[miss] = a[miss]
    over = (~miss) & (np.abs(out) > 1.7014117331926443e38)
    if over.any():
        out[over] = M.SYSMISS
    return out


def fits(a, t):
    """True if every non-missing value of a can be stored exactly as type t."""
    a = np.asarray(a, dtype=np.float64)
    v = a[a < M.SYSMISS]
    if t == "double":
        return True
    if t == "float":
        return bool(np.all(v.astype(np.float32).astype(np.float64) == v))
    lo, hi = RANGE[t]
    return bool(np.all((v == np.floor(v)) & (v >= lo) & (v <= hi)))


class Variable:
    __slots__ = ("name", "type", "data", "format", "label", "vlabel")

    def __init__(self, name, type, data, format=None, label="", vlabel=""):
        self.name = name
        self.type = type
        self.data = data
        self.format = format or default_format(type)
        self.label = label or ""
        self.vlabel = vlabel or ""

    @property
    def isstr(self):
        return is_str(self.type)

    def copy(self):
        return Variable(self.name, self.type, self.data.copy(), self.format, self.label, self.vlabel)


class Dataset:
    def __init__(self, vars=None, label="", value_labels=None, chars=None):
        self.vars = list(vars or [])
        self.label = label or ""
        self.value_labels = value_labels or {}
        self.chars = chars or {}
        self.sortedby = []
        self.varabbrev = True
        self.notes = {}
        self.filename = ""
        self.timestamp = ""
        self.changed = False

    # --- shape -----------------------------------------------------------
    @property
    def N(self):
        return len(self.vars[0].data) if self.vars else getattr(self, "_N", 0)

    def set_obs(self, n):
        old = self.N
        if n < old:
            raise StataError("observation number out of range", 198)
        for v in self.vars:
            extra = n - old
            if v.isstr:
                v.data = np.concatenate([v.data, np.array([""] * extra, dtype=object)])
            else:
                v.data = np.concatenate([v.data, np.full(extra, M.SYSMISS)])
        self._N = n

    # --- lookup ----------------------------------------------------------
    def names(self):
        return [v.name for v in self.vars]

    def has(self, name):
        return any(v.name == name for v in self.vars)

    def varindex(self, name):
        for i, v in enumerate(self.vars):
            if v.name == name:
                return i
        raise StataError(f"variable {name} not found", 111)

    def find(self, name, abbrev=None):
        """Resolve a single variable name, allowing unique abbreviations."""
        for v in self.vars:
            if v.name == name:
                return v
        if abbrev is None:
            abbrev = self.varabbrev
        if abbrev:
            hits = [v for v in self.vars if v.name.startswith(name)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise StataError(f"{name} ambiguous abbreviation", 111)
        raise StataError(f"variable {name} not found", 111)

    def var(self, name):
        return self.find(name)

    def expand_varlist(self, tokens, allow_new=False):
        """Expand a list of name patterns (wildcards, ranges) into names."""
        out = []
        names = self.names()
        toks = list(tokens)
        i = 0
        while i < len(toks):
            t = toks[i]
            if i + 2 < len(toks) and toks[i + 1] == "-":
                a = self.find(t).name
                b = self.find(toks[i + 2]).name
                ia, ib = names.index(a), names.index(b)
                if ia > ib:
                    raise StataError(f"{t}-{toks[i + 2]}: variables out of order", 111)
                out.extend(names[ia:ib + 1])
                i += 3
                continue
            if "-" in t and not t.startswith("-") and not t.endswith("-") and "*" not in t:
                a, b = t.split("-", 1)
                a, b = self.find(a).name, self.find(b).name
                ia, ib = names.index(a), names.index(b)
                if ia > ib:
                    raise StataError(f"{t}: variables out of order", 111)
                out.extend(names[ia:ib + 1])
            elif any(c in t for c in "*?~"):
                pat = t.replace("~", "?")
                hits = [n for n in names if fnmatch.fnmatchcase(n, pat)]
                if not hits:
                    raise StataError(f"variable {t} not found", 111)
                out.extend(hits)
            elif t == "_all":
                out.extend(names)
            else:
                if allow_new and not self._resolvable(t):
                    out.append(t)
                else:
                    out.append(self.find(t).name)
            i += 1
        return out

    def _resolvable(self, t):
        try:
            self.find(t)
            return True
        except StataError:
            return False

    # --- modification ----------------------------------------------------
    def add(self, var):
        if self.has(var.name):
            raise StataError(f"variable {var.name} already defined", 110)
        self.vars.append(var)
        self.changed = True

    def drop_vars(self, names):
        s = set(names)
        self.vars = [v for v in self.vars if v.name not in s]
        self.sortedby = [n for n in self.sortedby if n not in s] if not (s & set(self.sortedby)) else self.sortedby[:self._first_dropped(s)]
        self.changed = True
        if not self.vars:
            self._N = 0

    def _first_dropped(self, s):
        for i, n in enumerate(self.sortedby):
            if n in s:
                return i
        return len(self.sortedby)

    def keep_rows(self, mask):
        mask = np.asarray(mask, dtype=bool)
        for v in self.vars:
            v.data = v.data[mask]
        self.changed = True

    def take_rows(self, idx):
        for v in self.vars:
            v.data = v.data[idx]
        self.changed = True

    def clear(self):
        self.__init__()

    def copy(self):
        d = Dataset([v.copy() for v in self.vars], self.label, {k: dict(t) for k, t in self.value_labels.items()},
                    {k: dict(t) for k, t in self.chars.items()})
        d.sortedby = list(self.sortedby)
        d.varabbrev = self.varabbrev
        d.filename = self.filename
        d.timestamp = self.timestamp
        d._N = self.N
        return d

    def sort(self, names, stable=True):
        if self.N == 0 or not names:
            self.sortedby = list(names)
            return
        keys = []
        for n in reversed(names):
            v = self.find(n)
            keys.append(v.data.astype(str) if v.isstr else v.data)
        idx = np.lexsort(keys) if len(keys) > 1 else np.argsort(keys[0], kind="stable")
        self.take_rows(idx)
        self.sortedby = [self.find(n).name for n in names]
