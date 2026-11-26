"""Data management commands."""
import os
import re

import numpy as np

from .. import missing as M
from .. import expr as X
from ..dataset import Dataset, Variable, default_format, fits, is_str, to_float32, NUMERIC
from ..dta import read_dta, write_dta
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import opt_lookup, parse_options, parse_standard, split_top, unquote
from .core import path_of


def plural(n, one, many):
    return f"{n:,} {one if n == 1 else many}"


# --- evaluation helpers ------------------------------------------------------

def evaluator(it):
    ev = X.Evaluator(it)
    by = getattr(it, "by", None)
    if by is not None:
        gs, ge, byn, byN = by.row_arrays(it.ds.N)
        ev.byn, ev.byN = byn, byN
        ev.groups = list(zip(by.starts, by.ends))
        ev.groupstart, ev.groupend = gs, ge
    return ev


def eval_expr(it, text):
    node = X.parse(text)
    v = evaluator(it).eval(node)
    N = it.ds.N
    if isinstance(v, np.ndarray):
        if v.ndim == 0:
            v = v.item()
        else:
            return v
    if isinstance(v, str):
        return np.array([v] * N, dtype=object)
    return np.full(N, float(v))


def in_mask(it, text):
    N = it.ds.N
    m = np.zeros(N, dtype=bool)
    t = text.strip()
    if "/" in t:
        a, b = t.split("/", 1)
    else:
        a, b = t, t

    def pos(s):
        s = s.strip()
        if s in ("f", "first"):
            return 1
        if s in ("l", "last"):
            return N
        v = int(float(s))
        return N + v + 1 if v < 0 else v
    lo, hi = pos(a), pos(b)
    if lo < 1 or hi > N or lo > hi + 1:
        raise StataError("Obs. nos. out of range", 198)
    m[lo - 1:hi] = True
    return m


def row_mask(it, p):
    N = it.ds.N
    m = np.ones(N, dtype=bool)
    if p.in_:
        m &= in_mask(it, p.in_)
    if p.if_:
        v = eval_expr(it, p.if_)
        if v.dtype == object:
            raise StataError("type mismatch", 109)
        m &= v != 0
    return m


# --- reading and writing ----------------------------------------------------

@command("use", 1)
def cmd_use(it, rest):
    p = parse_standard(rest)
    o = opt_lookup(p.options, "clear nolabel")
    if p.using:
        fname = p.using
        varspec = p.varlist
    else:
        fname = unquote(p.varlist)
        varspec = ""
    if not os.path.splitext(fname)[1]:
        fname += ".dta"
    path = path_of(it, fname)
    if it.ds.changed and it.ds.N and "clear" not in o:
        raise StataError("no; dataset in memory has changed since last saved", 4)
    if not os.path.exists(path):
        raise StataError(f"file {fname} not found", 601)
    ds = read_dta(path)
    if varspec.strip():
        names = ds.expand_varlist(varspec.split())
        ds.vars = [v for v in ds.vars if v.name in set(names)]
    if p.if_ or p.in_:
        it2 = type("T", (), {})()
        it.ds = ds
        mask = row_mask(it, p)
        ds.keep_rows(mask)
    ds.varabbrev = it.settings.get("varabbrev", "on") == "on"
    ds.filename = path
    ds.changed = False
    it.ds = ds
    if ds.label:
        it.print(f"({ds.label})")


@command("save", 2)
def cmd_save(it, rest):
    p = parse_standard(rest)
    o = opt_lookup(p.options, "replace emptyok noLabel orphans")
    fname = unquote(p.varlist) if p.varlist.strip() else it.ds.filename
    if not fname:
        raise StataError("invalid file specification", 198)
    if not os.path.splitext(fname)[1]:
        fname += ".dta"
    path = path_of(it, fname)
    exists = os.path.exists(path)
    if exists and "replace" not in o:
        raise StataError(f"file {fname} already exists", 602)
    if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
        raise StataError(f"file {fname} could not be opened", 603)
    if not exists and "replace" in o and path in it.tempfiles:
        # Witnessed in HNPXO1 09_final_data_management: replace on a tempfile not yet written prints this note first.
        # No open log shows replace on another file that did not exist (the authors' outputs were already there),
        # so the note is printed for tempfiles only.
        it.print(f"(file {fname} not found)")
    it.ds.timestamp = write_dta(it.ds, path)
    it.ds.changed = False
    it.ds.filename = path
    # Witnessed in HNPXO1 08 and 09 (7 tempfile saves): a name whose extension is not .dta gets the format suffix.
    # Long notes wrap in the logs at a width the two witnesses do not pin (75 to 77); printed unwrapped here.
    dta = os.path.splitext(fname)[1].lower() == ".dta"
    it.print(f"file {fname} saved" if dta else f"file {fname} saved as .dta format")


# --- keep / drop -------------------------------------------------------------

def _keepdrop(it, rest, keep):
    p = parse_standard(rest, using=False)
    if p.if_ or p.in_:
        if p.varlist.strip():
            raise StataError("invalid syntax", 198)
        m = row_mask(it, p)
        if not keep:
            m = ~m
        n = int((~m).sum())
        it.ds.keep_rows(m)
        it.print(f"({plural(n, 'observation', 'observations')} deleted)")
        return
    names = it.ds.expand_varlist(p.varlist.split())
    if keep:
        names = [n for n in it.ds.names() if n not in set(names)]
    it.ds.drop_vars(names)


@command("keep")
def cmd_keep(it, rest):
    _keepdrop(it, rest, True)


@command("drop")
def cmd_drop(it, rest):
    if rest.strip() == "_all":
        it.ds.drop_vars(it.ds.names())
        return
    _keepdrop(it, rest, False)


# --- generate / replace ------------------------------------------------------

def _storage_for_new(it, typ, vals, isstr):
    if isstr:
        n = max([len(s.encode("utf-8")) for s in vals] + [1])
        if typ and typ.startswith("str"):
            return typ if typ == "strL" else f"str{max(int(typ[3:] or 1), 1) if typ[3:] else n}"
        return f"str{n}" if n <= 2045 else "strL"
    return typ or it.settings.get("type", "float")


def store_values(typ, vals):
    if typ == "float":
        return to_float32(vals)
    if typ in ("byte", "int", "long"):
        v = np.asarray(vals, dtype=np.float64)
        ok = v < M.SYSMISS
        out = v.copy()
        out[ok] = np.trunc(v[ok])
        return out
    return np.asarray(vals, dtype=np.float64)


@command("generate", 1)
def cmd_generate(it, rest):
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
    vl = None
    if ":" in name:
        name, vl = name.split(":", 1)
    if typ and not (typ in NUMERIC or re.match(r"^str(\d+|L|)$", typ)):
        raise StataError(f"{typ} invalid type", 198)
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$", name):
        raise StataError(f"{name} invalid name", 198)
    if it.ds.has(name):
        raise StataError(f"variable {name} already defined", 110)
    vals = eval_expr(it, p.exp)
    isstr = vals.dtype == object
    if typ and is_str(typ) != isstr:
        raise StataError("type mismatch", 109)
    m = row_mask(it, p)
    N = it.ds.N
    if isstr:
        data = np.where(m, vals, "").astype(object)
    else:
        data = np.where(m, vals, M.SYSMISS)
    typ = _storage_for_new(it, typ, data if isstr else None, isstr)
    if not isstr:
        data = store_values(typ, data)
        if typ in ("byte", "int", "long") and not fits(np.where(data >= M.SYSMISS, 0, data), typ):
            pass
    v = Variable(name, typ, data)
    if vl:
        v.vlabel = vl
    it.ds.add(v)
    if not isstr:
        nm = int((data >= M.SYSMISS).sum())
    else:
        nm = int((data == "").sum())
    if nm:
        it.print(f"({plural(nm, 'missing value', 'missing values')} generated)")


def _promote(typ, vals):
    """Smallest type at least as wide as typ that holds vals exactly."""
    order = ["byte", "int", "long", "float", "double"]
    if typ == "double":
        return typ
    v = np.asarray(vals, dtype=np.float64)
    nonint = np.any((v < M.SYSMISS) & (v != np.floor(v)))
    i = order.index(typ)
    for t in order[i:]:
        if t in ("byte", "int", "long"):
            if not nonint and fits(v, t):
                return t
        elif t == "float":
            if typ != "float" and (nonint or not fits(v, "long")):
                # replace promotes integer types to float, or double if needed
                return "float" if fits(v, "float") else "double"
            if typ == "float":
                return "float"
        else:
            return "double"
    return "double"


@command("replace")
def cmd_replace(it, rest):
    p = parse_standard(rest, using=False)
    if p.exp is None:
        raise StataError("invalid syntax", 198)
    name = p.varlist.strip()
    v = it.ds.find(name, abbrev=False) if not it.ds.varabbrev else it.ds.find(name)
    vals = eval_expr(it, p.exp)
    if (vals.dtype == object) != v.isstr:
        raise StataError("type mismatch", 109)
    m = row_mask(it, p)
    old = v.data
    if v.isstr:
        new = np.where(m, vals, old).astype(object)
        changed = int((new != old).sum())
        need = max([len(s.encode("utf-8")) for s in new] + [1])
        if v.type != "strL" and need > int(v.type[3:]):
            v.type = f"str{need}" if need <= 2045 else "strL"
            v.format = default_format(v.type)
        v.data = new
        tomiss = int(((new == "") & (old != "") & m).sum())
    else:
        cand = np.where(m, vals, old)
        newtyp = v.type
        if v.type in ("byte", "int", "long", "float"):
            sub = cand[m]
            if v.type == "float":
                newtyp = "float"
            else:
                newtyp = _promote(v.type, sub)
        new = store_values(newtyp, cand)
        new = np.where(m, new, old)
        changed = int(np.sum(new != old))
        tomiss = int(np.sum((new >= M.SYSMISS) & (new != old)))
        if newtyp != v.type:
            it.print(f"variable {v.name} was {v.type} now {newtyp}")
            v.type = newtyp
            v.format = default_format(newtyp) if v.format == default_format(v.type) else v.format
        v.data = new
    it.ds.changed = True
    msg = f"({plural(changed, 'real change', 'real changes')} made"
    if tomiss:
        msg += f", {tomiss:,} to missing"
    it.print(msg + ")")


# --- sorting -----------------------------------------------------------------

@command("sort", 2)
def cmd_sort(it, rest):
    p = parse_standard(rest, using=False)
    names = it.ds.expand_varlist(p.varlist.split())
    it.ds.sort(names)


@command("gsort")
def cmd_gsort(it, rest):
    main, _ = split_top(rest, ",")
    toks = main.split()
    keys = []
    for t in toks:
        desc = t.startswith("-")
        n = it.ds.find(t.lstrip("+-")).name
        keys.append((n, desc))
    arrs = []
    for n, desc in reversed(keys):
        d = it.ds.find(n).data
        if d.dtype == object:
            u, inv = np.unique(d.astype(str), return_inverse=True)
            d = inv.astype(np.float64)
        arrs.append(-d if desc else d)
    idx = np.lexsort(arrs)
    it.ds.take_rows(idx)
    it.ds.sortedby = [n for n, desc in keys if not desc] if not any(d for _, d in keys) else []


@command("order")
def cmd_order(it, rest):
    p = parse_standard(rest, using=False)
    o = opt_lookup(p.options, "first last before() after() alphabetic sequential")
    names = it.ds.expand_varlist(p.varlist.split())
    others = [v for v in it.ds.vars if v.name not in set(names)]
    moved = [it.ds.find(n) for n in names]
    if "last" in o:
        it.ds.vars = others + moved
    elif "before" in o or "after" in o:
        tgt = it.ds.find((o.get("before") or o.get("after")).strip()).name
        k = [v.name for v in others].index(tgt) + (1 if "after" in o else 0)
        it.ds.vars = others[:k] + moved + others[k:]
    else:
        it.ds.vars = moved + others


@command("rename", 3)
def cmd_rename(it, rest):
    w = rest.split()
    if len(w) != 2 or any(c in rest for c in "*?(") :
        raise Unsupported("rename group syntax")
    v = it.ds.find(w[0])
    if it.ds.has(w[1]):
        raise StataError(f"variable {w[1]} already defined", 110)
    old = v.name
    v.name = w[1]
    it.ds.sortedby = [w[1] if n == old else n for n in it.ds.sortedby]


# --- labels ------------------------------------------------------------------

@command("label", 3)
def cmd_label(it, rest):
    w = rest.split(None, 1)
    sub = w[0] if w else ""
    arg = w[1] if len(w) > 1 else ""
    if sub in ("variable", "var", "variab", "va", "v", "vari", "varia", "variabl"):
        m = re.match(r"^(\S+)\s*(.*)$", arg, re.S)
        v = it.ds.find(m.group(1))
        lab = unquote(m.group(2).strip())
        v.label = lab[:80]
        return
    if sub in ("data", "da", "dat"):
        it.ds.label = unquote(arg.strip())[:80]
        return
    if sub in ("define", "de", "def", "defi", "defin"):
        main, opts = split_top(arg, ",")
        o = parse_options(opts or "")
        toks = _label_tokens(main)
        name = toks[0]
        if name in it.ds.value_labels and not ("add" in o or "modify" in o or "replace" in o):
            raise StataError(f"label {name} already defined", 110)
        tbl = {} if "replace" in o or name not in it.ds.value_labels else dict(it.ds.value_labels[name])
        pairs = toks[1:]
        if len(pairs) % 2:
            raise StataError("invalid syntax", 198)
        for k in range(0, len(pairs), 2):
            val = pairs[k]
            if re.match(r"^\.[a-z]$", val):
                raise Unsupported("value labels for extended missing values")
            tbl[int(float(val))] = pairs[k + 1]
        it.ds.value_labels[name] = tbl
        return
    if sub in ("values", "val", "valu", "value"):
        toks = arg.split()
        lab = toks[-1] if len(toks) > 1 else ""
        names = it.ds.expand_varlist(toks[:-1] if len(toks) > 1 else toks)
        if lab == ".":
            lab = ""
        for n in names:
            it.ds.find(n).vlabel = lab
        return
    if sub in ("drop",):
        for n in arg.split():
            if n == "_all":
                it.ds.value_labels.clear()
            else:
                it.ds.value_labels.pop(n, None)
        return
    raise Unsupported(f"label {sub}")


def _label_tokens(s):
    out = []
    i = 0
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        if s.startswith('`"', i):
            j = s.find("\"'", i + 2)
            out.append(s[i + 2:j])
            i = j + 2
        elif s[i] == '"':
            j = s.find('"', i + 1)
            out.append(s[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(s) and not s[j].isspace():
                j += 1
            out.append(s[i:j])
            i = j
    return out


# --- compress / isid / count ----------------------------------------------------

SIZES = {"byte": 1, "int": 2, "long": 4, "float": 4, "double": 8}


@command("compress")
def cmd_compress(it, rest):
    p = parse_standard(rest, using=False)
    names = it.ds.expand_varlist(p.varlist.split()) if p.varlist.strip() else it.ds.names()
    saved = 0
    N = it.ds.N
    for n in names:
        v = it.ds.find(n)
        if v.isstr:
            if v.type == "strL":
                continue
            need = max([len(s.encode("utf-8")) for s in v.data] + [1])
            cur = int(v.type[3:])
            if need < cur:
                it.print(f"  variable {v.name} was {v.type} now str{need}")
                saved += (cur - need) * N
                v.type = f"str{need}"
                if v.format == f"%{cur}s":
                    v.format = f"%{need}s"
                elif v.format == f"%-{cur}s":
                    v.format = f"%-{need}s"
            continue
        for t in ("byte", "int", "long", "float"):
            if SIZES[t] >= SIZES[v.type]:
                break
            if t == "float" and v.type != "double":
                break
            if fits(v.data, t) and _ext_ok(v.data, t):
                it.print(f"  variable {v.name} was {v.type} now {t}")
                saved += (SIZES[v.type] - SIZES[t]) * N
                if v.format == default_format(v.type):
                    v.format = default_format(t)
                v.type = t
                break
    it.print(f"  ({saved:,} bytes saved)")


def _ext_ok(data, t):
    return True


@command("isid")
def cmd_isid(it, rest):
    p = parse_standard(rest, using=False)
    o = opt_lookup(p.options, "sort missok")
    names = it.ds.expand_varlist(p.varlist.split())
    cols = [it.ds.find(n).data for n in names]
    N = it.ds.N
    if "missok" not in o:
        for n, c in zip(names, cols):
            bad = (c == "") if c.dtype == object else (c >= M.SYSMISS)
            if bad.any():
                raise StataError(f"variable {n} should never be missing", 459)
    keys = list(zip(*[c.tolist() for c in cols])) if N else []
    if len(set(keys)) != N:
        vs = " ".join(names)
        raise StataError(f"variable{'s' if len(names) > 1 else ''} {vs} {'do' if len(names) > 1 else 'does'} not uniquely identify the observations", 459)
    if "sort" in o:
        it.ds.sort(names)


@command("count", 3)
def cmd_count(it, rest):
    p = parse_standard(rest, using=False)
    n = int(row_mask(it, p).sum())
    it.r = {"N": float(n)}
    it.print(f"  {n:,}")


# --- preserve / restore -------------------------------------------------------
# One level, as in the language: a second preserve before restore is an error. Data preserved inside a do-file
# come back when that do-file ends, on success or error (interp.run_file).

@command("preserve", 4)
def cmd_preserve(it, rest):
    o = opt_lookup(parse_options(split_top(rest, ",")[1] or ""), "changed")
    if split_top(rest, ",")[0].strip():
        raise StataError("invalid syntax", 198)
    if it.preserved is not None:
        raise StataError("already preserved", 621)
    it.preserved = it.ds.copy()
    it.preserved.changed = it.ds.changed
    del o


@command("restore", 4)
def cmd_restore(it, rest):
    o = opt_lookup(parse_options(split_top(rest, ",")[1] or ""), "NOT PREServe")
    if split_top(rest, ",")[0].strip():
        raise StataError("invalid syntax", 198)
    if it.preserved is None:
        raise StataError("nothing to restore", 622)
    if o.get("not"):
        it.preserved = None
        return
    keep = it.preserved
    it.ds = keep.copy()
    it.ds.changed = keep.changed
    it.preserved = keep if o.get("preserve") else None


# --- encode ----------------------------------------------------------------------

@command("encode")
def cmd_encode(it, rest):
    p = parse_standard(rest, using=False)
    o = opt_lookup(p.options, "Generate() Label() NOEXTend")
    if not o.get("generate"):
        raise StataError("option generate() required", 198)
    names = p.varlist.split()
    if len(names) != 1:
        raise StataError("too many variables specified" if names else "varlist required", 103 if names else 100)
    src = it.ds.find(names[0])
    if not src.isstr:
        raise StataError(f"{src.name} must be a string variable", 108)
    new = o["generate"].strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$", new):
        raise StataError(f"{new} invalid name", 198)
    if it.ds.has(new):
        raise StataError(f"variable {new} already defined", 110)
    lab = (o.get("label") or new).strip()
    m = row_mask(it, p)
    vals = src.data
    existing = dict(it.ds.value_labels.get(lab, {}))
    by_text = {}
    for k, t in sorted(existing.items()):
        by_text.setdefault(t, k)
    wanted = sorted({s for s, ok in zip(vals, m) if ok and s != ""})
    missing_text = [s for s in wanted if s not in by_text]
    if missing_text and o.get("noextend"):
        raise StataError(f"there are values of {src.name} not in label {lab}", 459)
    nxt = max(existing, default=0) + 1
    for s in missing_text:
        while nxt in existing:
            nxt += 1
        existing[nxt] = s
        by_text[s] = nxt
        nxt += 1
    data = np.array([float(by_text[s]) if ok and s != "" else M.SYSMISS for s, ok in zip(vals, m)],
                    dtype=np.float64)
    v = Variable(new, "long", data)
    v.vlabel = lab
    v.label = src.label
    it.ds.value_labels[lab] = existing
    it.ds.add(v)
