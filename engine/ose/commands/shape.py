"""Data-shaping commands: collapse and reshape.

collapse: one observation per by-group, each result a statistic of one source
variable over that group's non-missing values. Written from the documented
behaviour, in our own words; checked against authors' logs in the open set.

Storage types of results (INFERRED, not yet witnessed in an authors' log that
describes collapsed data; see docs/decisions.md "collapse result types"):
  count            -> long
  sum, rawsum      -> double
  min max first last firstnm lastnm -> the source variable's type and format
  every other stat -> double if the source is double, else float
"""
import json
import re

import numpy as np

from .. import missing as M
from ..dataset import NUMERIC, Dataset, Variable, default_format, fits, to_float32
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import opt_lookup, parse_standard
from .byprefix import groups_of
from .data import row_mask
from .summ import pctile

STATS = {"mean", "sum", "rawsum", "count", "max", "min", "sd", "semean", "median", "first", "last",
         "firstnm", "lastnm", "iqr", "percent"}
KEEP_TYPE = {"min", "max", "first", "last", "firstnm", "lastnm"}


def _stat_name(s):
    s = s.strip().lower()
    if s in STATS:
        return s
    m = re.fullmatch(r"p(\d{1,2})", s)
    if m and 1 <= int(m.group(1)) <= 99:
        return s
    if s in ("sebinomial", "sepoisson", "cv"):
        raise Unsupported(f"collapse statistic ({s})")
    raise StataError(f"{s} is not a valid statistic", 198)


def parse_clist(ds, text):
    """Return [(stat, target, source)] in the order written."""
    out = []
    stat = "mean"
    toks = re.findall(r"\([^)]*\)|[^\s=]+\s*=\s*[^\s=]+|\S+", text)
    for t in toks:
        if t.startswith("("):
            stat = _stat_name(t[1:-1])
            continue
        if "=" in t:
            tgt, src = [x.strip() for x in t.split("=", 1)]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", tgt):
                raise StataError(f"{tgt} invalid name", 198)
            out.append((stat, tgt, ds.find(src).name))
            continue
        for n in ds.expand_varlist([t]):
            out.append((stat, n, n))
    if not out:
        raise StataError("varlist required", 100)
    return out


def _one(stat, x, ok, total_n):
    """Statistic of one group. x: values, ok: non-missing mask."""
    v = x[ok]
    n = len(v)
    if stat == "count":
        return float(n)
    if stat in ("first", "last"):
        return float(x[0] if stat == "first" else x[-1]) if len(x) else M.SYSMISS
    if stat in ("sum", "rawsum"):
        return float(np.sum(v)) if n else 0.0
    if stat == "percent":
        return 100.0 * n / total_n if total_n else M.SYSMISS
    if n == 0:
        return M.SYSMISS
    if stat == "firstnm":
        return float(v[0])
    if stat == "lastnm":
        return float(v[-1])
    if stat == "mean":
        return float(np.mean(v))
    if stat == "min":
        return float(np.min(v))
    if stat == "max":
        return float(np.max(v))
    if stat in ("sd", "semean"):
        if n < 2:
            return M.SYSMISS
        sd = float(np.sqrt(np.sum((v - np.mean(v)) ** 2) / (n - 1)))
        return sd if stat == "sd" else sd / np.sqrt(n)
    s = np.sort(v)
    if stat == "median":
        return float(pctile(s, 50))
    if stat == "iqr":
        return float(pctile(s, 75) - pctile(s, 25))
    return float(pctile(s, int(stat[1:])))


@command("collapse")
def cmd_collapse(it, rest):
    p = parse_standard(rest, using=False)
    if p.weight:
        raise Unsupported("collapse with weights")
    o = opt_lookup(p.options, "by() cw fast")
    ds = it.ds
    clist = p.varlist + ("=" + p.exp if p.exp is not None else "")  # collapse has no =exp: rejoin
    items = parse_clist(ds, clist)
    byv = ds.expand_varlist(o["by"].split()) if o.get("by") else []
    targets = [t for _, t, _ in items]
    for t in targets:
        if targets.count(t) > 1 or t in byv:
            raise StataError(f"{t} already defined" if t not in byv else
                             f"{t} is both a by-variable and a result", 110 if t not in byv else 198)
    for _, _, s in items:
        if ds.find(s).isstr:
            raise Unsupported("collapse of a string variable")
    m = row_mask(it, p)
    if o.get("cw"):
        for _, _, s in items:
            m &= ~M.is_missing(ds.find(s).data)
    work = Dataset([v.copy() for v in ds.vars if v.name in set(byv) | {s for _, _, s in items}])
    work.keep_rows(m)
    if work.N == 0:
        raise StataError("no observations", 2000)
    if byv:
        work.sort(byv)
        starts, ends = groups_of(work, byv)
    else:
        starts, ends = [0], [work.N]
    G = len(starts)
    new = Dataset(label=ds.label, value_labels={k: dict(t) for k, t in ds.value_labels.items()},
                  chars={k: dict(t) for k, t in ds.chars.items()})
    for b in byv:
        src = work.find(b)
        new.vars.append(Variable(src.name, src.type, src.data[starts],
                                 src.format, src.label, src.vlabel))
    for stat, tgt, s in items:
        src = work.find(s)
        x = src.data
        ok_all = ~M.is_missing(x)
        total_n = int(ok_all.sum())
        vals = np.array([_one(stat, x[a:b], ok_all[a:b], total_n) for a, b in zip(starts, ends)],
                        dtype=np.float64)
        vals = M.clean(vals) if stat not in ("first", "last") else vals
        if stat == "count":
            typ, fmt = "long", default_format("long")
        elif stat in ("sum", "rawsum"):
            typ, fmt = "double", default_format("double")
        elif stat in KEEP_TYPE:
            typ, fmt = src.type, src.format
        else:
            typ = "double" if src.type == "double" else "float"
            fmt = default_format(typ)
        if typ == "float":
            vals = to_float32(vals)
        label = f"({stat}) {src.label or src.name}"
        new.vars.append(Variable(tgt, typ, vals, fmt, label, src.vlabel if stat in KEEP_TYPE else ""))
    if not new.vars:
        raise StataError("no variables", 102)
    new._N = G
    new.sortedby = list(byv)
    new.filename = ds.filename
    new.changed = True
    it.ds = new


_RESHAPE_SPEC = "_ose_reshape"
_RESHAPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}")
_NUMERIC_SUFFIX = re.compile(r"0|[1-9][0-9]*")


def _reshape_spec(ds, rest):
    p = parse_standard(rest, using=False)
    head = p.varlist.split()
    if not head or head[0] not in ("long", "wide"):
        raise Unsupported("reshape syntax other than reshape long or wide")
    direction, *stubs = head
    if p.if_ is not None or p.in_ is not None or p.weight or p.exp is not None:
        raise Unsupported("reshape with a qualifier, weight or expression")
    if not stubs and not p.options:
        saved = ds.chars.get("_dta", {}).get(_RESHAPE_SPEC)
        if not saved:
            raise StataError("reshape requires stubs, i() and j() on its first call", 198)
        try:
            spec = json.loads(saved)
            if (not isinstance(spec, list) or len(spec) != 4
                    or any(not isinstance(part, list) or not part
                           or any(not isinstance(n, str) for n in part) for part in spec[:2])
                    or not isinstance(spec[2], str) or type(spec[3]) is not bool):
                raise ValueError
        except ValueError:
            raise StataError("invalid saved reshape specification", 198) from None
        return direction, *spec

    options = p.options
    if options.keys() - {"i", "j", "string"}:
        raise Unsupported("reshape options other than i(), j() and string")
    if "string" in options and options["string"] is not True:
        raise StataError("string does not take an argument", 198)
    id_spec, j = options.get("i"), options.get("j")
    if not stubs or not isinstance(id_spec, str) or not isinstance(j, str):
        raise StataError("reshape requires stubs, i() and j()", 198)
    if not all(_RESHAPE_NAME.fullmatch(stub) for stub in stubs):
        raise Unsupported("reshape stub patterns")
    j = j.strip()
    if not _RESHAPE_NAME.fullmatch(j):
        raise Unsupported("reshape requires a single j variable name")
    ids = ds.expand_varlist(id_spec.split())
    if not ids or len(set(ids + [j] + stubs)) != len(ids) + len(stubs) + 1:
        raise StataError("reshape requires distinct i(), j() and stub names", 198)
    return direction, stubs, ids, j, "string" in options


def _rename_column(source, data, name=None, typ=None):
    return Variable(name or source.name, typ or source.type, data,
                    source.format, source.label, source.vlabel)


def _reshape_order(ds, keys):
    cols = [ds.find(key).data for key in keys]
    order = np.lexsort(cols[::-1])
    starts = np.zeros(ds.N, dtype=bool)
    starts[0] = True
    for col in cols:
        ordered = col[order]
        starts[1:] |= ordered[1:] != ordered[:-1]
    return order, starts


def _reshape_blank(var, size):
    return np.full(size, "", dtype=object) if var.isstr else np.full(size, M.SYSMISS)


def _reshape_type(cols):
    first = cols[0]
    if any(v.isstr != first.isstr for v in cols):
        raise StataError("reshape cannot combine numeric and string columns for a stub", 109)
    if first.isstr:
        if any(v.type == "strL" for v in cols):
            return "strL"
        return max((v.type for v in cols), key=lambda t: int(t[3:]))
    widest = max(NUMERIC.index(v.type) for v in cols)
    return next(t for t in NUMERIC[widest:] if all(fits(v.data, t) for v in cols))


def _reshape_long(ds, stubs, ids, j, string):
    if ds.has(j):
        raise StataError(f"variable {j} already defined", 110)
    order, unique = _reshape_order(ds, ids)
    if not unique.all():
        raise StataError(f"i() variables {' '.join(ids)} do not uniquely identify observations", 9)

    sources = {stub: {} for stub in stubs}
    for var in ds.vars:
        if var.name in ids:
            continue
        suffixes = [(stub, var.name[len(stub):]) for stub in stubs
                    if var.name.startswith(stub) and var.name != stub]
        matches = [(stub, suffix if string else int(suffix)) for stub, suffix in suffixes
                   if string or _NUMERIC_SUFFIX.fullmatch(suffix)]
        if not matches and any(re.fullmatch(r"0[0-9]+", suffix) for _, suffix in suffixes):
            raise Unsupported("reshape numeric suffixes with leading zeros; use string")
        if len(matches) > 1:
            raise Unsupported(f"reshape: {var.name} matches multiple stubs")
        if matches:
            stub, value = matches[0]
            sources[stub][value] = var
    for stub, cols in sources.items():
        if not cols:
            raise StataError(f"no columns found for reshape stub {stub}", 111)

    values = sorted({value for cols in sources.values() for value in cols})
    if not string and any(int(float(value)) != value for value in values):
        raise Unsupported("reshape suffixes that cannot be stored exactly as numbers")
    used = {v.name for cols in sources.values() for v in cols.values()}
    repeating = [v for v in ds.vars if v.name not in used and v.name not in ids]
    if any(v.name in stubs for v in repeating):
        raise StataError("reshape stub already exists as a variable", 110)

    n_values = len(values)
    rows = np.repeat(order, n_values)
    out = [_rename_column(ds.find(key), ds.find(key).data[rows]) for key in ids]
    j_values = np.array(values, dtype=object if string else np.float64)
    if string:
        j_width = max(len(value.encode("utf-8")) for value in values)
        j_type = f"str{j_width}"
    else:
        j_type = next(t for t in ("int", "long", "double") if fits(j_values, t))
    out.append(Variable(j, j_type, np.tile(j_values, ds.N)))
    pairs = []
    for stub, cols in sources.items():
        present = [cols[value] for value in values if value in cols]
        result = _reshape_blank(present[0], len(rows)).reshape(ds.N, n_values)
        for k, value in enumerate(values):
            if value in cols:
                result[:, k] = cols[value].data[order]
        out.append(_rename_column(present[0], result.ravel(), stub, _reshape_type(present)))
        pairs.append(([v.name for v in present], [stub]))
    out.extend(_rename_column(v, v.data[rows]) for v in repeating)
    return out, values, pairs


def _reshape_wide(ds, stubs, ids, j, string):
    jvar = ds.find(j, abbrev=False)
    if string != jvar.isstr:
        raise StataError("j() variable type does not match the string option", 109)
    if string:
        if np.any(jvar.data == ""):
            raise StataError("j() variable contains empty values", 9)
    elif np.any(M.is_missing(jvar.data) | (jvar.data < 0) | (np.floor(jvar.data) != jvar.data)):
        raise Unsupported("reshape wide with missing, negative or fractional numeric j() values")
    wide_cols = [ds.find(stub, abbrev=False) for stub in stubs]
    order, new_group = _reshape_order(ds, ids)
    values, positions = np.unique(jvar.data[order], return_inverse=True)
    group = np.cumsum(new_group) - 1
    n_groups = int(new_group.sum())
    if len(set(zip(group, positions))) != ds.N:
        raise StataError(f"j() variable {j} is not unique within i() variables {' '.join(ids)}", 9)
    values = values.tolist() if string else [int(v) for v in values]
    first = order[new_group]

    repeating = [v for v in ds.vars if v.name not in ids + [j] + stubs]
    out = [_rename_column(ds.find(key), ds.find(key).data[first]) for key in ids]
    occupied = set(ids) | {v.name for v in repeating}
    pairs = []
    for src in wide_cols:
        names = [src.name + str(value) for value in values]
        for name in names:
            if not _RESHAPE_NAME.fullmatch(name):
                raise StataError(f"invalid reshape variable name {name}", 198)
            if name in occupied:
                raise StataError(f"variable {name} already defined", 110)
            occupied.add(name)
        data = _reshape_blank(src, len(values) * n_groups).reshape(len(values), n_groups)
        data[positions, group] = src.data[order]
        out.extend(_rename_column(src, col, name) for name, col in zip(names, data))
        pairs.append(([src.name], names))
    for v in repeating:
        data = v.data[first]
        if not np.array_equal(v.data[order], data[group]):
            raise StataError(f"variable {v.name} varies within i() variables {' '.join(ids)}", 9)
        out.append(_rename_column(v, data))
    return out, values, pairs


def _reshape_summary(it, before, after, direction, values, j, pairs):
    def row(label, old, new):
        it.print(f"{label}{old:>{max(1, 39 - len(label))}}   ->   {new}")

    def listed(names):
        if len(names) > 3:
            names = [*names[:2], "...", names[-1]]
        return " ".join(names)

    wide = direction == "wide"
    it.print_wrapped("(j = " + " ".join(map(str, values)) + ")")
    it.print()
    row("Data", "Long" if wide else "Wide", "Wide" if wide else "Long")
    it.print("-" * 77)
    row("Number of observations", f"{before.N:,}", f"{after.N:,}")
    row("Number of variables", f"{len(before.vars):,}", f"{len(after.vars):,}")
    row(f"j variable ({len(values)} values)", j if wide else "", "(dropped)" if wide else j)
    it.print("xij variables:")
    for old, new in pairs:
        row("", listed(old), listed(new))
    it.print("-" * 77)


@command("reshape")
def cmd_reshape(it, rest):
    ds = it.ds
    direction, stubs, ids, j, string = _reshape_spec(ds, rest)
    if ds.N == 0:
        raise StataError("no observations", 2000)
    convert = _reshape_long if direction == "long" else _reshape_wide
    columns, values, pairs = convert(ds, stubs, ids, j, string)
    retained = {v.name for v in columns}
    chars = {name: dict(attrs) for name, attrs in ds.chars.items() if name in retained or name == "_dta"}
    chars.setdefault("_dta", {})[_RESHAPE_SPEC] = json.dumps([stubs, ids, j, string])
    out = Dataset(columns, ds.label, {k: dict(v) for k, v in ds.value_labels.items()}, chars)
    out.sortedby = ids + [j] if direction == "long" else ids.copy()
    out.varabbrev = ds.varabbrev
    out.filename = ds.filename
    out.notes = dict(ds.notes)
    out.changed = True
    it.ds = out
    _reshape_summary(it, ds, out, direction, values, j, pairs)
