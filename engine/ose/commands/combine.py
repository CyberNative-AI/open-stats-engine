"""Combine datasets along keys (merge) or rows (append)."""
import os
import re
from struct import error as StructError

import numpy as np

from .. import missing as M
from ..dataset import Dataset, NUMERIC, Variable
from ..dta import read_dta
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import find_keyword, opt_lookup, parse_options, parse_standard, split_top, unquote
from .core import path_of

MERGE_CODES = {
    "master": 1, "using": 2, "match": 3, "matched": 3,
    "match_update": 4, "match_conflict": 5,
}
MERGE_LABELS = {1: "Master only (1)", 2: "Using only (2)", 3: "Matched (3)",
                4: "Missing updated (4)", 5: "Nonmissing conflict (5)"}
NOTE = re.compile(r"note([0-9]+)")
FILE = re.compile(r"""(?:`".*?"'|"[^"]*"|[^\s"`]+)(?=\s|$)""")


def _parse(rest, spec):
    main, opt_text = split_top(rest)
    using = find_keyword(main, "using")
    if using < 0:
        raise StataError("using required", 100)
    head = main[:using].strip()
    rest = main[using + 5:].strip()
    files = []
    while rest:
        token = FILE.match(rest)
        if not token or not unquote(token[0]):
            raise StataError("invalid file specification", 198)
        files.append(unquote(token[0]))
        rest = rest[token.end():].lstrip()
    if not files:
        raise StataError("invalid file specification", 198)

    forms = {item.lower().removesuffix("()"): item.endswith("()") for item in spec.split()}
    options = {}
    for name, value in parse_options(opt_text or "").items():
        try:
            option, = opt_lookup({name: value}, spec)
        except StataError:
            raise Unsupported(f"option {name}") from None
        if option not in forms:
            raise Unsupported(f"option {name}")
        if option in options or forms[option] == (value is True):
            raise StataError(f"invalid option {name}", 198)
        if isinstance(value, str) and not value.strip():
            raise StataError(f"option {name} requires an argument", 198)
        options[option] = value
    return head, files, options


def _read(it, filename):
    if not os.path.splitext(filename)[1]:
        filename += ".dta"
    try:
        ds = read_dta(path_of(it, filename))
    except FileNotFoundError:
        raise StataError(f"file {filename} not found", 601) from None
    except OSError:
        raise StataError(f"file {filename} could not be opened", 603) from None
    except (ValueError, StructError) as error:
        if str(error).startswith("dta: unsupported release"):
            raise Unsupported(str(error)) from None
        raise StataError(f"file {filename} is not a valid dataset", 610) from None
    ds.varabbrev = it.ds.varabbrev
    return ds


def _gen_name(options, default=None):
    if "nogenerate" in options:
        if "generate" in options:
            raise StataError("generate() and nogenerate cannot be combined", 198)
        return None
    name = options.get("generate", default)
    if name and not re.fullmatch(r"[^\W\d]\w{0,31}", name.strip()):
        raise StataError(f"{name} invalid name", 198)
    return name.strip() if name else None


def _select_codes(options, name):
    if name not in options:
        return None
    codes = set()
    for word in options[name].split():
        if word in MERGE_CODES:
            codes.add(MERGE_CODES[word])
        elif word in ("1", "2", "3", "4", "5"):
            codes.add(int(word))
        else:
            raise Unsupported(f"{name}({word})")
    return sorted(codes)


def _promoted_type(left, right):
    if left.isstr:
        if "strL" in (left.type, right.type):
            return "strL"
        return max((left.type, right.type), key=lambda kind: int(kind[3:]))
    if {left.type, right.type} == {"long", "float"}:
        # A float cannot represent every long integer.
        return "double"
    return max((left.type, right.type), key=NUMERIC.index)


def _combine_type(left, right, force, messages):
    if left.isstr != right.isstr:
        if not force:
            raise StataError(f"variable {left.name} is {left.type} in master but {right.type} in using data", 106)
        messages.append(f"(using values of {left.name} treated as missing due to a type conflict)")
        return None
    kind = _promoted_type(left, right)
    if kind != left.type:
        messages.append(f"(variable {left.name} was {left.type}, now {kind} to accommodate using data's values)")
    return kind


def _missing_column(var, size):
    if var.isstr:
        return np.full(size, "", dtype=object)
    return np.full(size, M.SYSMISS)


def _metadata(primary, sources, names, options):
    """Copy the master metadata once, taking additional definitions in source order."""
    labels = {name: table.copy() for name, table in primary.value_labels.items()}
    chars = {name: attrs.copy() for name, attrs in primary.chars.items() if name in names or name == "_dta"}
    for source in sources:
        if "nolabel" not in options:
            for name, table in source.value_labels.items():
                if name not in labels:
                    labels[name] = table.copy()
        for name, attrs in source.chars.items():
            if name != "_dta" and name not in names:
                continue
            dest = chars.setdefault(name, {})
            notes = []
            for key, value in attrs.items():
                note = NOTE.fullmatch(key)
                if not note:
                    dest.setdefault(key, value)
                elif key != "note0" and "nonotes" not in options:
                    notes.append((int(note[1]), value))
            if notes:
                count = int(dest.get("note0", "0"))
                for _, value in sorted(notes):
                    count += 1
                    dest[f"note{count}"] = value
                dest["note0"] = str(count)
    return labels, chars


def _result(master, columns, row_count, labels, chars):
    ds = Dataset(columns, master.label, labels, chars)
    ds._N = row_count
    ds.varabbrev = master.varabbrev
    ds.filename = master.filename
    ds.changed = True
    return ds


def _key_rows(columns, side, unique, sorted_):
    keys = list(zip(*(var.data for var in columns)))
    if sorted_ and any(old > new for old, new in zip(keys, keys[1:])):
        raise StataError(f"{side} data not sorted", 5)
    if unique and len(set(keys)) != len(keys):
        names = " ".join(var.name for var in columns)
        subject = f"variable {names} does" if len(columns) == 1 else f"variables {names} do"
        raise StataError(f"{subject} not uniquely identify observations in the {side} data", 459)
    return keys


def _pair_rows(master_keys, using_keys, using_unique):
    """Return parallel row indices, using -1 for a missing side of the join."""
    outer, inner = (master_keys, using_keys) if using_unique else (using_keys, master_keys)
    lookup = {key: i for i, key in enumerate(inner)}
    paired = np.fromiter((lookup.get(key, -1) for key in outer), dtype=np.intp, count=len(outer))
    used = np.zeros(len(inner), dtype=bool)
    used[paired[paired >= 0]] = True
    unmatched = np.flatnonzero(~used)
    outer_idx = np.concatenate((np.arange(len(outer)), np.full(len(unmatched), -1, dtype=np.intp)))
    inner_idx = np.concatenate((paired, unmatched))
    return (outer_idx, inner_idx) if using_unique else (inner_idx, outer_idx)


def _merge_column(left, right, rows, update, replace, codes, messages, force):
    mi, ui = rows
    has_master = mi >= 0
    has_using = ui >= 0
    var = left if left is not None else right
    data = _missing_column(var, len(mi))
    kind = var.type
    if left is not None and right is not None:
        promoted = _combine_type(left, right, force, messages)
        if promoted is None:
            right = None
        else:
            kind = promoted
    if left is not None:
        data[has_master] = left.data[mi[has_master]]
    if right is not None:
        use = has_using if left is None else has_using & ~has_master
        data[use] = right.data[ui[use]]
        if update and left is not None:
            matched = np.flatnonzero(has_master & has_using)
            current, incoming = data[matched], right.data[ui[matched]]
            if left.isstr:
                current_missing, incoming_missing = current == "", incoming == ""
            else:
                current_missing, incoming_missing = M.is_missing(current), M.is_missing(incoming)
            fill = current_missing & ~incoming_missing
            conflict = ~current_missing & ~incoming_missing & (current != incoming)
            codes[matched[fill]] = np.maximum(codes[matched[fill]], 4)
            codes[matched[conflict]] = 5
            write = fill | conflict if replace else fill
            data[matched[write]] = incoming[write]
    return Variable(var.name, kind, data, var.format, var.label, var.vlabel)


def _report(it, counts, name):
    # HNPXO1, 09_final_data_management.log: kept rows only; omit the
    # master/using detail when both counts are zero.
    _, master, using, matched = counts[:4]
    rule = "    " + "-" * 41
    it.print()
    it.print("    Result                      Number of obs")
    it.print(rule)
    it.print(f"    {'Not matched':<29}{master + using:>12,}")
    if master or using:
        for label, count, code in (("from master", master, 1), ("from using", using, 2)):
            tag = f"  ({name}=={code})" if name else ""
            it.print(f"        {label:<25}{count:>12,}{tag}")
        it.print()
    tag = f"  ({name}==3)" if name else ""
    it.print(f"    {'Matched':<29}{matched:>12,}{tag}")
    it.print(rule)


@command("merge", 3)
def cmd_merge(it, rest):
    head, files, options = _parse(
        rest, "keep() assert() GENerate() NOGENerate keepusing() update replace nolabel nonotes force noreport sorted",
    )
    if not head:
        raise StataError("merge requires a cardinality and key varlist", 198)
    cardinality, *tail = head.split(maxsplit=1)
    keys = tail[0] if tail else ""
    if cardinality == "m:m":
        raise Unsupported("merge m:m (use keyed 1:1, m:1, or 1:m)")
    if cardinality not in ("1:1", "m:1", "1:m"):
        raise Unsupported(f"merge cardinality {cardinality or '(missing)'}")
    key_spec = parse_standard(keys, using=False)
    if key_spec.if_ is not None or key_spec.in_ is not None or key_spec.weight or key_spec.exp is not None:
        raise Unsupported("merge qualifiers")
    if len(files) != 1 or not key_spec.varlist:
        raise StataError("merge requires a key varlist and one using file", 198)
    if "replace" in options and "update" not in options:
        raise StataError("replace requires update", 198)
    name = _gen_name(options, "_merge")
    keep = _select_codes(options, "keep")
    allowed = _select_codes(options, "assert")

    master = it.ds
    using = _read(it, files[0])
    names = master.expand_varlist(key_spec.varlist.split())
    if len(set(names)) != len(names):
        raise StataError("duplicate merge key", 198)
    left_keys = [master.find(key, abbrev=False) for key in names]
    right_keys = [using.find(key, abbrev=False) for key in names]
    for left, right in zip(left_keys, right_keys):
        if left.isstr != right.isstr:
            raise StataError(f"key variable {left.name} is {left.type} in master but {right.type} in using data", 106)
        if "strL" in (left.type, right.type):
            raise Unsupported("merge with strL keys")
    from_using = set(using.expand_varlist(options["keepusing"].split())) if "keepusing" in options else set(using.names())
    from_using.update(names)
    if name and (master.has(name) or name in from_using):
        raise StataError(f"variable {name} already defined", 110)
    left_rows = _key_rows(left_keys, "master", cardinality != "m:1", "sorted" in options)
    right_rows = _key_rows(right_keys, "using", cardinality != "1:m", "sorted" in options)
    mi, ui = _pair_rows(left_rows, right_rows, cardinality != "1:m")
    codes = np.where(ui < 0, 1, np.where(mi < 0, 2, 3))

    left_vars = {v.name: v for v in master.vars}
    right_vars = {v.name: v for v in using.vars if v.name in from_using}
    messages = []
    columns = [
        _merge_column(left_vars.get(key), right_vars.get(key), (mi, ui), "update" in options and key not in names,
                      "replace" in options, codes, messages, "force" in options)
        for key in (left_vars | right_vars)
    ]
    retained = {var.name for var in columns}
    labels, chars = _metadata(master, [using], retained, options)
    failed = allowed is not None and not np.isin(codes, allowed).all()
    if keep is not None and not failed:
        selected = np.isin(codes, keep)
        codes = codes[selected]
        for var in columns:
            var.data = var.data[selected]
    if "update" in options and "noreport" not in options:
        raise Unsupported("merge update result table")
    if name:
        label_name = name
        match_labels = {i: label for i, label in MERGE_LABELS.items() if i <= 3 or "update" in options}
        if label_name in labels and labels[label_name] != match_labels:
            label_name = name[:25] + "_result"
            if label_name in labels and labels[label_name] != match_labels:
                raise Unsupported("merge result value-label name collision")
        labels[label_name] = match_labels
        columns.append(Variable(name, "byte", codes.astype(float), label="Matching result from merge",
                                vlabel=label_name))
    ds = _result(master, columns, len(codes), labels, chars)
    # Use ascending key order and retain many-side input order within ties.
    # HNPXO1 09_final_data_management sets sortseed and sorts again before
    # the final save, so its transcript witnesses counts but does not resolve ties.
    ds.sort(names)
    it.ds = ds
    for message in messages:
        it.print(message)
    if "noreport" not in options:
        _report(it, np.bincount(codes, minlength=6), name)
    if failed:
        raise StataError("merge assertion failed (merged data left in memory)", 9)


@command("append", 3)
def cmd_append(it, rest):
    head, files, options = _parse(rest, "GENerate() keep() force nolabel")
    if head:
        raise Unsupported("append arguments before using")
    name = _gen_name(options)
    master = it.ds
    sources = [_read(it, filename) for filename in files]
    source_vars = [{v.name: v for v in source.vars} for source in sources]
    available = {}
    for vs in source_vars:
        for key, var in vs.items():
            available.setdefault(key, var)
    if "keep" in options:
        using_vars = Dataset(available.values())
        using_vars.varabbrev = master.varabbrev
        selected = set(using_vars.expand_varlist(options["keep"].split()))
        source_vars = [{key: var for key, var in vs.items() if key in selected} for vs in source_vars]

    master_vars = {v.name: v for v in master.vars}
    templates = dict(master_vars)
    for vs in source_vars:
        for key, var in vs.items():
            templates.setdefault(key, var)
    if name and name in templates:
        raise StataError(f"variable {name} already defined", 110)

    sizes = [master.N] + [source.N for source in sources]
    pieces = {key: [] for key in templates}
    schema = {}
    messages = []
    # Visit sources in file order, including notices for intermediate widening.
    for size, vs in zip(sizes, [master_vars] + source_vars):
        for key, template in templates.items():
            var = vs.get(key)
            if var is not None:
                existing = schema.get(key)
                if existing is None:
                    schema[key] = Variable(key, var.type, None, var.format, var.label, var.vlabel)
                else:
                    kind = _combine_type(existing, var, "force" in options, messages)
                    if kind is None:
                        var = None
                    else:
                        existing.type = kind
            pieces[key].append(var.data if var is not None else _missing_column(template, size))

    columns = list(schema[key] for key in templates)
    for var in columns:
        var.data = np.concatenate(pieces[var.name])
    if name:
        kind = "byte" if len(files) <= 100 else "int" if len(files) <= 32740 else "long"
        data = np.repeat(np.arange(len(sizes), dtype=float), sizes)
        columns.append(Variable(name, kind, data))
    empty_master = not master.vars and not master.N
    primary = sources[0] if empty_master else master
    labels, chars = _metadata(master, sources, templates.keys(), options)
    it.ds = _result(primary, columns, sum(sizes), labels, chars)
    it.ds.filename = master.filename
    for message in messages:
        it.print(message)
