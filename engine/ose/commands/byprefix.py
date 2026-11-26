"""The by/bysort prefix."""
import re

import numpy as np

from ..errors import StataError, Unsupported
from ..syntax import split_top

# Commands that understand by-groups through the expression context.
BY_EXPR = {"generate", "replace", "keep", "drop", "egen"}


class ByInfo:
    def __init__(self, keys, sortvars, starts, ends):
        self.keys = keys
        self.sortvars = sortvars
        self.starts = starts      # group start index (0-based) per group
        self.ends = ends          # group end (exclusive) per group

    def row_arrays(self, N):
        gs = np.empty(N, dtype=np.int64)
        ge = np.empty(N, dtype=np.int64)
        byn = np.empty(N, dtype=np.float64)
        byN = np.empty(N, dtype=np.float64)
        for s, e in zip(self.starts, self.ends):
            gs[s:e] = s
            ge[s:e] = e - 1
            byn[s:e] = np.arange(1, e - s + 1)
            byN[s:e] = e - s
        return gs, ge, byn, byN


def groups_of(ds, keys):
    N = ds.N
    if N == 0:
        return [], []
    change = np.zeros(N, dtype=bool)
    change[0] = True
    for k in keys:
        d = ds.find(k).data
        if d.dtype == object:
            change[1:] |= d[1:] != d[:-1]
        else:
            change[1:] |= d[1:] != d[:-1]
    starts = np.nonzero(change)[0]
    ends = np.append(starts[1:], N)
    return list(starts), list(ends)


def is_sorted_by(ds, names):
    if ds.sortedby[:len(names)] == names:
        return True
    N = ds.N
    if N <= 1:
        return True
    keys = [ds.find(n).data for n in names]
    # check lexicographic order
    order = np.lexsort([k.astype(str) if k.dtype == object else k for k in reversed(keys)])
    return bool(np.all(order == np.arange(N)))


def run_by(it, rest, sort):
    m = split_top(rest, ":")
    head, cmd = m
    if cmd is None:
        raise StataError("invalid syntax", 198)
    head, opts = split_top(head, ",")
    if opts and "sort" in opts.split():
        sort = True
    mm = re.match(r"^([^()]*)(?:\(([^)]*)\))?\s*$", head.strip())
    if not mm:
        raise StataError("invalid syntax", 198)
    keys = it.ds.expand_varlist(mm.group(1).split())
    sv = it.ds.expand_varlist(mm.group(2).split()) if mm.group(2) else []
    if sort:
        it.ds.sort(keys + sv)
    elif not is_sorted_by(it.ds, keys + sv):
        raise StataError("not sorted", 5)
    starts, ends = groups_of(it.ds, keys)
    word = cmd.strip().split(None, 1)[0]
    from ..interp import lookup
    hit = lookup(word)
    if hit is None:
        raise Unsupported(f"command {word}")  # not built yet: exit 2, as at top level
    from ..interp import REGISTRY
    name = [k for k, v in REGISTRY.items() if v is hit][0]
    if name not in BY_EXPR:
        raise Unsupported(f"by prefix with {name}")
    it.by = ByInfo(keys, sv, starts, ends)
    try:
        it.dispatch(cmd.strip())
    finally:
        it.by = None
