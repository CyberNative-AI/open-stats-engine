"""Display formats (%w.dg, %w.df, %w.de, %ws, comma variants).

Behaviour of the automatic %g layout is learned from published logs and
pinned by tests; see docs/decisions.md.
"""
import math
import re

from . import missing as M

FMT_RE = re.compile(r"^%(-)?(0)?(\d+)(?:\.(\d+))?([gfe])(c)?$")
SFMT_RE = re.compile(r"^%(-)?(\d+)s$")


def strip0(s):
    if "." in s and "e" not in s:
        s = s.rstrip("0").rstrip(".")
    return s


def lead(s):
    """Drop the leading zero of numbers between -1 and 1 ('0.5' -> '.5')."""
    if s.startswith("0."):
        return s[1:]
    if s.startswith("-0."):
        return "-" + s[2:]
    return s


def gnum(x, w=9):
    """Automatic %w.0g text for a finite number (no padding)."""
    if x >= M.SYSMISS:
        return M.missing_label(x)
    if x == 0:
        return "0"
    ax = abs(x)
    budget = w - 1
    if float(x).is_integer() and len(str(int(ax))) <= budget:
        return str(int(x))
    nint = len(str(int(ax))) if ax >= 1 else 0
    if nint <= budget and ax >= 1e-4:
        dec = max(budget - nint - 1, 0)
        s = lead(strip0(f"{x:.{dec}f}"))
        if s not in ("", "-", ".", "-.") and len(s.lstrip("-")) <= budget:
            return s
    mant = max(budget - 6, 0)
    s = f"{x:.{mant}e}"
    m, e = s.split("e")
    m = strip0(m) if "." in m else m
    return f"{m}e{e[0]}{int(e[1:]):02d}"


def commas(s):
    neg = s.startswith("-")
    if neg:
        s = s[1:]
    ip, _, fp = s.partition(".")
    ip = f"{int(ip):,}" if ip else ""
    return ("-" if neg else "") + ip + (("." + fp) if fp or _ else "")


def fmt_num(x, f):
    """Format a number with a display format, returning a padded string."""
    m = FMT_RE.match(f)
    if not m:
        raise ValueError(f"bad format {f}")
    left, zero, w, d, kind, comma = m.groups()
    w = int(w)
    if x >= M.SYSMISS:
        s = M.missing_label(x)
    elif kind == "g":
        if d and int(d) > 0:
            s = f"{x:.{int(d)}g}"
            s = lead(s)
        else:
            s = gnum(x, w)
        if comma:
            s = commas(s) if "e" not in s else s
    elif kind == "f":
        s = f"{x:.{int(d or 0)}f}"
        if comma:
            s = commas(s)
    else:
        s = f"{x:.{int(d or 0)}e}"
        mm, e = s.split("e")
        s = f"{mm}e{e[0]}{int(e[1:]):02d}"
    if zero and not left:
        return s.rjust(w, "0") if not s.startswith("-") else "-" + s[1:].rjust(w - 1, "0")
    return s.ljust(w) if left else s.rjust(w)


def fmt_str(s, f):
    m = SFMT_RE.match(f)
    if not m:
        return s
    w = int(m.group(2))
    return s.ljust(w) if m.group(1) else s.rjust(w)


def fmt_any(x, f):
    if isinstance(x, str):
        return fmt_str(x, f)
    if f.startswith("%t") or f.startswith("%-t"):
        from .dates import fmt_date
        return fmt_date(x, f)
    return fmt_num(x, f)


def fmt_width(f):
    m = re.match(r"^%-?0?(\d+)", f)
    return int(m.group(1)) if m else 9
