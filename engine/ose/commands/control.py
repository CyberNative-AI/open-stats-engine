"""Loops, conditionals and program definitions."""
import re

import numpy as np

from .. import missing as M
from ..errors import StataError, Unsupported
from ..interp import Block, command

MAXITER = 10_000_000


def _run_body(it, block):
    it.run_tree(block.body, echo=False)


class _Break(Exception):
    pass


def run_block(it, block):
    head = it.macro.expand(block.head.text).strip()
    head = head[:-1].rstrip()  # drop '{'
    word = head.split(None, 1)[0] if head else ""
    rest = head[len(word):].strip()
    if word in ("foreach",):
        return _foreach(it, rest, block)
    if word in ("forvalues", "forval", "forv", "forva", "forvalu", "forvalue"):
        return _forvalues(it, rest, block)
    if word == "while":
        return _while(it, block)
    if word == "if":
        return _if(it, rest, block)
    if word == "else":
        if rest.startswith("if"):
            return _if(it, rest[2:].strip(), block, is_else=True)
        if it._else_pending:
            it._else_pending = False
            _run_body(it, block)
        return
    if word in ("quietly", "qui", "quietl"):
        it.quiet += 1
        try:
            _run_body(it, block)
        finally:
            it.quiet -= 1
        return
    if word in ("noisily", "noi"):
        q = it.quiet
        it.quiet = 0
        try:
            _run_body(it, block)
        finally:
            it.quiet = q
        return
    if word in ("capture", "cap", "capt"):
        it.quiet += 1
        try:
            _run_body(it, block)
            it.rc = 0
        except StataError as e:
            it.rc = e.rc
        finally:
            it.quiet -= 1
        return
    raise Unsupported(f"block starting with {word}")


def _foreach(it, rest, block):
    m = re.match(r"^([A-Za-z_]\w*)\s+(in|of)\s*(.*)$", rest, re.S)
    if not m:
        raise StataError("invalid syntax", 198)
    name, kind, lst = m.groups()
    if kind == "in":
        items = _split_items(lst)
    else:
        m2 = re.match(r"^(local|global|varlist|newlist|numlist)\s+(.*)$", lst.strip(), re.S)
        if not m2:
            raise StataError("invalid syntax", 198)
        k2, arg = m2.groups()
        if k2 == "local":
            items = _split_items(it.locals.get(arg.strip(), ""))
        elif k2 == "global":
            items = _split_items(it.globals.get(arg.strip(), ""))
        elif k2 == "varlist":
            items = it.ds.expand_varlist(arg.split())
        elif k2 == "newlist":
            items = arg.split()
        else:
            items = [it.num_to_macro(x) for x in numlist(arg)]
    for v in items:
        it.locals[name] = v
        _run_body(it, block)


def _split_items(s):
    out = []
    i = 0
    s = s.strip()
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


def numlist(s):
    """Expand a numlist: '1/5', '1(2)9', '10 20 30', '1 2 to 10'."""
    out = []
    toks = s.replace(",", " ").split()
    for t in toks:
        m = re.match(r"^(-?[\d.]+)\s*/\s*(-?[\d.]+)$", t)
        m2 = re.match(r"^(-?[\d.]+)\((-?[\d.]+)\)(-?[\d.]+)$", t)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            step = 1 if b >= a else -1
            x = a
            while (x <= b + 1e-12) if step > 0 else (x >= b - 1e-12):
                out.append(x)
                x += step
        elif m2:
            a, st, b = (float(m2.group(k)) for k in (1, 2, 3))
            n = int(np.floor((b - a) / st + 1e-9)) + 1
            out.extend(a + st * k for k in range(max(n, 0)))
        else:
            try:
                out.append(float(t))
            except ValueError:
                raise StataError(f"invalid numlist", 121)
    return out


def _forvalues(it, rest, block):
    m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", rest, re.S)
    if not m:
        raise StataError("invalid syntax", 198)
    name, rng = m.groups()
    rng = rng.replace(" ", "")
    m1 = re.match(r"^(-?[\d.]+)/(-?[\d.]+)$", rng)
    m2 = re.match(r"^(-?[\d.]+)\((-?[\d.]+)\)(-?[\d.]+)$", rng)
    m3 = re.match(r"^(-?[\d.]+)(-?[\d.]+)to(-?[\d.]+)$", rng)
    if m1:
        a, b = float(m1.group(1)), float(m1.group(2))
        st = 1.0
    elif m2:
        a, st, b = (float(m2.group(k)) for k in (1, 2, 3))
    else:
        raise Unsupported(f"forvalues range {rng}")
    x = a
    k = 0
    while (x <= b + 1e-12) if st > 0 else (x >= b - 1e-12):
        it.locals[name] = it.num_to_macro(round(x, 12))
        _run_body(it, block)
        k += 1
        x = a + st * k
        if k > MAXITER:
            raise StataError("too many iterations", 198)


def _while(it, block):
    k = 0
    while True:
        cond = it.macro.expand(block.head.text).strip()[len("while"):-1].strip()
        v = it.eval_scalar_expr(cond)
        if isinstance(v, str) or v == 0:
            break
        _run_body(it, block)
        k += 1
        if k > MAXITER:
            raise StataError("too many iterations", 198)


def _if(it, cond, block, is_else=False):
    if is_else and not it._else_pending:
        return
    v = it.eval_scalar_expr(cond)
    if isinstance(v, str):
        raise StataError("type mismatch", 109)
    if v != 0:
        it._else_pending = False
        _run_body(it, block)
    else:
        it._else_pending = True


@command("if", raw=True)
def cmd_if(it, rest):
    """One-line `if exp command`."""
    # rest = "exp command"; split at the first top-level position where the
    # expression ends. We try progressively longer prefixes.
    toks = rest.split(" ")
    for k in range(1, len(toks)):
        cond = " ".join(toks[:k])
        cmd = " ".join(toks[k:])
        try:
            from .. import expr as X
            X.parse(cond)
        except StataError:
            continue
        try:
            X.parse(" ".join(toks[:k + 1]))
            continue
        except StataError:
            pass
        v = it.eval_scalar_expr(cond)
        if v != 0:
            it._else_pending = False
            it.dispatch(cmd)
        else:
            it._else_pending = True
        return
    raise StataError("invalid syntax", 198)


@command("else", raw=True)
def cmd_else(it, rest):
    if it._else_pending:
        it._else_pending = False
        it.dispatch(rest)


@command("continue", raw=True)
def cmd_continue(it, rest):
    raise Unsupported("continue")
