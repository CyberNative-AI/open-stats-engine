"""Read the witnessed comma-delimited forms of import delimited and insheet."""

from codecs import BOM_UTF8
import csv
import io
from decimal import Decimal, localcontext
import re

import numpy as np

from .. import missing as M
from ..dataset import FLOAT_MAX, RANGE, Dataset, Variable, fits, to_float32
from ..errors import StataError, Unsupported
from ..interp import command
from ..syntax import parse_options, split_top, unquote
from .core import path_of


FILE = re.compile(r"""(?:"[^"]*"|`".*"'|[^\s"`]+)""")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
MISSING = {"": M.SYSMISS, ".": M.SYSMISS, **{"." + k: v for k, v in M.EXT.items()}}
RESERVED = {"_all", "_b", "_coef", "_cons", "_n", "_N", "_pi", "_pred", "_rc", "_se", "_skip", "_weight"}


@command("import")
def cmd_import(it, rest):
    words = rest.split(maxsplit=1)
    if not words or words[0].lower() != "delimited":
        raise Unsupported("import subcommand other than delimited")
    _import_csv(it, words[1] if len(words) == 2 else "", delimited=True)


@command("insheet")
def cmd_insheet(it, rest):
    _import_csv(it, rest, delimited=False)


def _arguments(rest, delimited):
    file, options = split_top(rest)
    file = file.strip()
    words = file.split(maxsplit=1)
    if words and words[0].lower() == "using":
        file = words[1] if len(words) == 2 else ""
    if not FILE.fullmatch(file) or not unquote(file):
        raise StataError("invalid file specification", 198)

    clear = False
    header = False
    for name, value in parse_options(options or "").items():
        key = name.lower()
        if key == "clear" and value is True:
            clear = True
        elif delimited and key in {"varname", "varnames"} and value is not True and value.strip() == "1":
            header = True
        elif not delimited and key == "comma" and value is True:
            continue
        else:
            raise Unsupported(f"import option {name}")
    return unquote(file), clear, header


def _unquoted_separator(text):
    """Return the first tab or semicolon outside a quoted field, or None.

    Follows the csv module's default dialect: a quote opens a quoted field only at
    the start of a field, and a doubled quote inside one is a literal quote.
    """
    if "\t" not in text and ";" not in text:
        return None
    start, plain, quoted, closing = range(4)
    state = start
    for char in text:
        if state == quoted:
            if char == '"':
                state = closing
            continue
        if state == closing and char == '"':
            state = quoted
            continue
        if char in "\t;":
            return char
        if char in ",\r\n":
            state = start
        elif state == start and char == '"':
            state = quoted
        else:
            state = plain
    return None


def _read_csv(path, encoding):
    with open(path, encoding=encoding, newline="") as stream:
        bom = stream.buffer.peek(3).startswith(BOM_UTF8)
        text = stream.read()
    # The reader splits on commas only. A tab or semicolon outside quotes may be
    # the file's real delimiter, so refuse rather than guess at the columns.
    if _unquoted_separator(text) is not None:
        raise Unsupported("tab or semicolon outside quotes (the reader splits on commas only)")
    rows = [row for row in csv.reader(io.StringIO(text, newline=""), strict=True) if row]
    if not rows:
        raise StataError("no observations", 2000)
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise Unsupported("delimited records with different field counts")
    return rows, bom


def _numeric(field):
    token = field.strip()
    if token in MISSING:
        return MISSING[token]
    if NUMBER.fullmatch(token) is None:
        return None
    return float(token)


def _keeps_written_digits(token, value):
    """True unless token is an integer whose written digits the stored value loses."""
    with localcontext() as context:
        context.prec = 800  # every finite binary64 integer has at most 309 digits
        exact = Decimal(token)
        if exact != exact.to_integral_value():
            return True
        last = Decimal((0, (1,), max(exact.as_tuple().exponent, 0)))
        return Decimal(value).quantize(last) == exact


def _storage(data, decimal_type):
    """Return the storage type for a numeric column and the values it stores."""
    for kind in RANGE:
        if fits(data, kind):
            return kind, data
    finite = data[data < M.SYSMISS]
    if np.all(finite == np.floor(finite)):
        # Integers beyond long: no published log witnesses their storage yet.
        # fits() keeps float to exact values inside the float range.
        return ("float" if fits(data, "float") else "double"), data
    # Decimals take the session's default numeric type, as `generate` does
    # (decisions §10, PXAPMY zinb models 1 and 12).
    # `set type double` stores the nearest binary64 value (about 15-17 digits).
    if decimal_type == "double":
        return "double", data
    if np.any(np.abs(finite) > FLOAT_MAX):
        raise Unsupported("decimal field outside the float range")
    return "float", to_float32(data)


# Integers below these magnitudes are exact in the type, so only larger ones
# need the written-digit check.
EXACT_BELOW = {"float": 2**24, "double": 2**53}


def _variable(name, label, fields, decimal_type):
    values = [_numeric(field) for field in fields]
    if None in values:
        width = max(1, max(len(field.encode("utf-8")) for field in fields))
        if width > 2045:
            raise Unsupported("string columns that require strL")
        return Variable(name, f"str{width}", np.array(fields, dtype=object), label=label)

    if any(field.strip() not in MISSING and not abs(value) <= M.MAXDOUBLE
           for field, value in zip(fields, values)):
        raise Unsupported("numeric field outside the supported range")
    kind, stored = _storage(np.array(values, dtype=np.float64), decimal_type)
    # Check the original tokens against the value the chosen type stores. An
    # integer token must keep every digit it writes, in any notation:
    # 9007199254740993 and 9.007199254740993e15 write a units digit binary64
    # cannot hold, and 16777217 one that float cannot hold, so each refuses in
    # that type; 3.5e38 writes two digits, and a double keeps them.
    limit = EXACT_BELOW.get(kind)
    if limit is not None:
        for field, value in zip(fields, stored):
            if value < M.SYSMISS and abs(value) >= limit and not _keeps_written_digits(field.strip(), value):
                raise Unsupported(f"integer field cannot be represented exactly as {kind}")
    return Variable(name, kind, stored, label=label)


def _column_names(fields, delimited):
    used = set(RESERVED)
    for index, field in enumerate(fields, start=1):
        text = field.strip()
        base = re.sub(r"[^A-Za-z0-9_]", "_" if delimited else "", text).lower()
        base = base or f"v{index}"
        if base[0].isdigit():
            base = "_" + base
        name = base[:32]
        number = 1
        while name in used:
            suffix = str(number)
            name = base[:32 - len(suffix)] + suffix
            number += 1
        used.add(name)
        # import delimited keeps any changed heading as the label. insheet keeps it
        # when only the case changed (AZEOHU open case, log line 28: a frequency table headed
        # with the upper-case CSV heading of a lower-case variable);
        # no log shows the label of a heading insheet stripped of punctuation.
        relabel = text != name and (delimited or text.lower() == name)
        yield name, text[:80] if relabel else ""


def _import_csv(it, rest, delimited):
    file, clear, header = _arguments(rest, delimited)
    if not clear and it.ds.changed and (it.ds.vars or it.ds.N):
        raise StataError("no; dataset in memory has changed since last saved", 4)

    path = path_of(it, file)
    latin1 = False
    try:
        try:
            rows, bom = _read_csv(path, "utf-8-sig")
            if delimited and not bom:
                latin1 = all(field.isascii() for row in rows for field in row)
        except UnicodeDecodeError:
            rows, _ = _read_csv(path, "iso-8859-1")
            latin1 = True
    except FileNotFoundError as error:
        raise StataError(f"file {file} not found", 601) from error
    except OSError as error:
        raise StataError(f"file {file} could not be opened", 603) from error
    except csv.Error as error:
        raise Unsupported("malformed or oversized delimited record") from error

    first = rows[0]
    if any("\x00" in field for row in rows for field in row):
        raise Unsupported("NUL byte in delimited input")
    if header or (any(field.strip() for field in first)
                  and all(not field.strip() or _numeric(field) is None for field in first)):
        names = _column_names(rows.pop(0), delimited)
    else:
        names = _column_names([""] * len(first), delimited)
    # zip has no columns for a header-only file, so supply an empty column per name.
    columns = zip(*rows) if rows else ((),) * len(first)
    decimal_type = "double" if it.settings.get("type", "float") == "double" else "float"
    dataset = Dataset([_variable(name, label, column, decimal_type) for (name, label), column in zip(names, columns)])
    dataset.varabbrev = it.settings.get("varabbrev", "on") == "on"
    dataset.changed = True
    it.ds = dataset
    if delimited and latin1:
        it.print("(encoding automatically selected: ISO-8859-1)")
    it.print(f"({len(dataset.vars):,} vars, {dataset.N:,} obs)")
