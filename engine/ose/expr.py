"""Expression parsing and vectorised evaluation.

An expression is parsed once into a small tree and evaluated against the
current dataset. Numeric results are float64 arrays (or Python floats for
scalar contexts) using the missing encoding in missing.py; string results are
object arrays or Python str.
"""
import math
import re

import numpy as np

from . import missing as M
from .errors import StataError, Unsupported

TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<miss>\.[a-z]?(?![A-Za-z0-9_]))
  | (?P<cstr>`"(?:(?!"').)*"')
  | (?P<str>"[^"]*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
  | (?P<op>==|!=|~=|>=|<=|&&|\|\||[-+*/^<>!~&|(),\[\]=:])
""", re.X)

BINARY = {
    "|": (1, "L"), "&": (2, "L"),
    "==": (3, "L"), "!=": (3, "L"), "~=": (3, "L"), ">": (3, "L"), "<": (3, "L"), ">=": (3, "L"), "<=": (3, "L"),
    "+": (4, "L"), "-": (4, "L"),
    "*": (5, "L"), "/": (5, "L"),
    "^": (7, "L"),
}
UNARY_MINUS_PREC = 6
NOT_PREC = 8


def tokenize(s):
    toks = []
    i = 0
    while i < len(s):
        m = TOKEN.match(s, i)
        if not m:
            raise StataError(f"{s[i:]} invalid name", 198)
        kind = m.lastgroup
        if kind != "ws":
            toks.append((kind, m.group(0)))
        i = m.end()
    return toks


class Node:
    __slots__ = ("k", "a")

    def __init__(self, k, *a):
        self.k = k
        self.a = a

    def __repr__(self):
        return f"{self.k}{self.a}"


class Parser:
    def __init__(self, s):
        self.s = s
        self.t = tokenize(s)
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, v):
        k, t = self.next()
        if t != v:
            raise StataError(f"invalid syntax", 198)

    def parse(self):
        if not self.t:
            raise StataError("invalid syntax", 198)
        n = self.expr(0)
        if self.i != len(self.t):
            raise StataError(f"invalid syntax", 198)
        return n

    def expr(self, minp):
        left = self.unary()
        while True:
            k, t = self.peek()
            if t == "=" and k == "op":
                raise StataError("invalid syntax", 198)
            if k != "op" or t not in BINARY:
                break
            p, assoc = BINARY[t]
            if p < minp:
                break
            self.next()
            right = self.expr(p + 1)
            left = Node("bin", t, left, right)
        return left

    def unary(self):
        k, t = self.peek()
        if k == "op" and t == "-":
            self.next()
            return Node("neg", self.expr(UNARY_MINUS_PREC))
        if k == "op" and t == "+":
            self.next()
            return self.expr(UNARY_MINUS_PREC)
        if k == "op" and t in ("!", "~"):
            self.next()
            return Node("not", self.expr(3))
        return self.atom()

    def atom(self):
        k, t = self.next()
        if k == "num":
            return Node("num", float(t))
        if k == "miss":
            return Node("num", M.SYSMISS if t == "." else M.EXT[t[1]])
        if k == "str":
            return Node("str", t[1:-1])
        if k == "cstr":
            return Node("str", t[2:-2])
        if k == "op" and t == "(":
            n = self.expr(0)
            self.expect(")")
            return n
        if k == "name":
            nk, nt = self.peek()
            if nt == "(" and "." not in t:
                self.next()
                args = []
                if self.peek()[1] != ")":
                    while True:
                        args.append(self.expr(0))
                        if self.peek()[1] == ",":
                            self.next()
                            continue
                        break
                self.expect(")")
                return Node("call", t, args)
            if nt == "[":
                self.next()
                if t in ("_b", "_se", "_coef"):
                    j = self.i
                    depth = 0
                    while j < len(self.t):
                        if self.t[j][1] == "]" and depth == 0:
                            break
                        depth += self.t[j][1] == "["
                        depth -= self.t[j][1] == "]"
                        j += 1
                    inner = "".join(x[1] for x in self.t[self.i:j])
                    self.i = j + 1
                    return Node("coef", t, inner)
                sub = self.expr(0)
                self.expect("]")
                return Node("sub", t, sub)
            return Node("var", t)
        raise StataError("invalid syntax", 198)


_cache = {}


def parse(s):
    n = _cache.get(s)
    if n is None:
        n = Parser(s).parse()
        if len(_cache) > 5000:
            _cache.clear()
        _cache[s] = n
    return n


# --- evaluation --------------------------------------------------------------

def _isstr(v):
    return isinstance(v, str) or (isinstance(v, np.ndarray) and v.dtype == object)


def _num(v):
    if _isstr(v):
        raise StataError("type mismatch", 109)
    return v


def _miss(v):
    return np.asarray(v) >= M.SYSMISS


def _arith(op, a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    bad = (a >= M.SYSMISS) | (b >= M.SYSMISS)
    with np.errstate(all="ignore"):
        if op == "+":
            r = a + b
        elif op == "-":
            r = a - b
        elif op == "*":
            r = a * b
        elif op == "/":
            r = a / b
            bad = bad | (b == 0)
        else:
            r = np.power(a, b)
    r = M.clean(r)
    return np.where(bad, M.SYSMISS, r)


def _tobool(v):
    return np.asarray(v, dtype=np.float64) != 0


class Evaluator:
    """Evaluate a parsed expression. ctx supplies data and named values."""

    def __init__(self, interp, rows=None):
        self.it = interp
        self.ds = interp.ds
        self.N = self.ds.N
        self.rows = rows  # optional index array for by-groups (_n/_N)
        self.byn = None
        self.byN = None

    def eval(self, node):
        f = getattr(self, "e_" + node.k)
        return f(*node.a)

    def e_num(self, v):
        return v

    def e_str(self, v):
        return v

    def e_neg(self, a):
        v = _num(self.eval(a))
        return np.where(_miss(v), M.SYSMISS, -np.asarray(v, dtype=np.float64)) if isinstance(v, np.ndarray) else (M.SYSMISS if v >= M.SYSMISS else -v)

    def e_not(self, a):
        v = _num(self.eval(a))
        r = (np.asarray(v, dtype=np.float64) == 0).astype(np.float64)
        return r if isinstance(v, np.ndarray) else float(r)

    def e_bin(self, op, a, b):
        x = self.eval(a)
        y = self.eval(b)
        sx, sy = _isstr(x), _isstr(y)
        if sx or sy:
            if not (sx and sy):
                raise StataError("type mismatch", 109)
            if op == "+":
                return _strcat(x, y)
            if op in ("==", "!=", "~=", "<", ">", "<=", ">="):
                return _strcmp(op, x, y)
            raise StataError("type mismatch", 109)
        scalar = not isinstance(x, np.ndarray) and not isinstance(y, np.ndarray)
        if op in "+-*/^":
            r = _arith(op, x, y)
        elif op == "&":
            r = (_tobool(x) & _tobool(y)).astype(np.float64)
        elif op == "|":
            r = (_tobool(x) | _tobool(y)).astype(np.float64)
        else:
            xa = np.asarray(x, dtype=np.float64)
            ya = np.asarray(y, dtype=np.float64)
            r = {"==": xa == ya, "!=": xa != ya, "~=": xa != ya, "<": xa < ya, ">": xa > ya,
                 "<=": xa <= ya, ">=": xa >= ya}[op].astype(np.float64)
        return float(r) if scalar else r

    def e_var(self, name):
        if name == "_n":
            return self._n()
        if name == "_N":
            return self._N()
        if name == "_pi":
            return math.pi
        if name in ("_rc",):
            return float(self.it.rc)
        if name in ("c", "r", "e"):
            raise StataError("invalid syntax", 198)
        if "." in name:
            raise Unsupported(f"factor or time-series operator in expression: {name}")
        try:
            v = self.ds.find(name)
        except StataError:
            if name in self.it.scalars:
                return self.it.scalars[name]
            raise
        if self.rows is not None:
            return v.data[self.rows]
        return v.data

    def _n(self):
        if self.byn is not None:
            return self.byn
        n = self.N if self.rows is None else len(self.rows)
        return np.arange(1, n + 1, dtype=np.float64)

    def _N(self):
        if self.byN is not None:
            return self.byN
        if self.scalar:
            # display, macros, forvalues bounds: rows is only the "observation 1" placeholder,
            # so _N is the dataset's observation count
            return float(self.N)
        return float(self.N if self.rows is None else len(self.rows))

    def e_sub(self, name, sub):
        idx = self.eval(sub)
        v = self.ds.find(name).data
        idx = np.asarray(idx, dtype=np.float64)
        if self.rows is not None and not self.scalar:
            # by-group rows; in scalar context (display, macros) rows is just "observation 1" and an
            # explicit subscript still addresses the whole dataset
            v = v[self.rows]
        n = len(v)
        if self.byn is not None and self.groups is not None:
            # subscripts inside by-groups are relative to the group start
            base = self.groupstart
            absi = base + idx - 1
            gend = self.groupend
            ok = (idx >= 1) & (absi <= gend) & (idx < M.SYSMISS)
            ii = np.where(ok, absi, 0).astype(np.int64)
        else:
            ok = (idx >= 1) & (idx <= n) & (idx < M.SYSMISS)
            ii = np.where(ok, idx - 1, 0).astype(np.int64)
            ii = np.broadcast_to(ii, (n,)) if ii.ndim == 0 else ii
            ok = np.broadcast_to(ok, (n,)) if np.ndim(ok) == 0 else ok
        ii = np.floor(ii).astype(np.int64)
        if v.dtype == object:
            return np.where(ok, v[ii], "")
        return np.where(ok, v[ii], M.SYSMISS)

    groups = None
    scalar = False

    def e_coef(self, kind, inner):
        return self.it.coef_value(kind, inner)

    def e_call(self, name, args):
        if name in ("r", "e", "c", "s"):
            if len(args) != 1 or args[0].k != "var":
                raise StataError("invalid syntax", 198)
            return self.it.result_value(name, args[0].a[0])
        fn = FUNCS.get(name)
        if fn is None:
            raise Unsupported(f"function {name}()")
        if name in LAZY:
            return fn(self, args)
        vals = [self.eval(a) for a in args]
        return fn(self, *vals)


def _strcat(x, y):
    if isinstance(x, str) and isinstance(y, str):
        return x + y
    xa = np.asarray(x, dtype=object)
    ya = np.asarray(y, dtype=object)
    return np.array(np.char.add(xa.astype(str), ya.astype(str)), dtype=object)


def _strcmp(op, x, y):
    if isinstance(x, str) and isinstance(y, str):
        return float({"==": x == y, "!=": x != y, "~=": x != y, "<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op])
    xa = np.asarray(x, dtype=object).astype(str)
    ya = np.asarray(y, dtype=object).astype(str)
    r = {"==": xa == ya, "!=": xa != ya, "~=": xa != ya, "<": xa < ya, ">": xa > ya, "<=": xa <= ya, ">=": xa >= ya}[op]
    return r.astype(np.float64)


# --- functions -------------------------------------------------------------

def _vec(f, *arrs):
    """Apply a float function elementwise, propagating missing."""
    scalar = all(not isinstance(a, np.ndarray) for a in arrs)
    aa = [np.asarray(a, dtype=np.float64) for a in arrs]
    bad = np.zeros(np.broadcast(*aa).shape, dtype=bool)
    for a in aa:
        bad = bad | (a >= M.SYSMISS)
    with np.errstate(all="ignore"):
        r = f(*aa)
    r = np.where(bad, M.SYSMISS, M.clean(r))
    return float(r) if scalar else r


def _round(ev, x, y=1.0):
    def f(a, b):
        with np.errstate(all="ignore"):
            q = a / b
            return np.where(b == 0, a, np.floor(q + 0.5) * b)
    return _vec(f, x, y)


def _missing(ev, *vals):
    out = None
    for v in vals:
        m = (np.asarray(v, dtype=object) == "") if _isstr(v) else _miss(v)
        out = m if out is None else (out | m)
    scalar = all(not isinstance(v, np.ndarray) for v in vals)
    r = np.asarray(out, dtype=np.float64)
    return float(r) if scalar else r


def _inlist(ev, x, *vals):
    out = None
    for v in vals:
        if _isstr(x) != _isstr(v):
            raise StataError("type mismatch", 109)
        m = np.asarray(x == v) if not (_isstr(x) and isinstance(x, np.ndarray)) else (np.asarray(x, dtype=object) == v)
        out = m if out is None else (out | m)
    r = np.asarray(out, dtype=np.float64)
    return float(r) if not isinstance(r, np.ndarray) or r.ndim == 0 else r


def _inrange(ev, x, a, b):
    x = np.asarray(x, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    lo = np.where(a >= M.SYSMISS, -np.inf, a)
    r = ((x >= lo) & (x <= b) & ~((x >= M.SYSMISS) & (b < M.SYSMISS))).astype(np.float64)
    return float(r) if r.ndim == 0 else r


def _cond(ev, args):
    c = ev.eval(args[0])
    a = ev.eval(args[1])
    b = ev.eval(args[2])
    if len(args) == 4:
        d = ev.eval(args[3])
        cc = np.asarray(c, dtype=np.float64)
        r = np.where(cc >= M.SYSMISS, d, np.where(cc != 0, a, b))
    else:
        r = np.where(np.asarray(c, dtype=np.float64) != 0, a, b)
    if r.ndim == 0:
        return r.item()
    return r


def _rowfn(kind):
    def f(ev, *vals):
        aa = np.broadcast_arrays(*[np.asarray(v, dtype=np.float64) for v in vals])
        st = np.vstack([a.ravel() for a in aa])
        mm = st >= M.SYSMISS
        if kind == "min":
            r = np.where(mm, np.inf, st).min(axis=0)
        else:
            r = np.where(mm, -np.inf, st).max(axis=0)
        r = np.where(mm.all(axis=0), M.SYSMISS, r)
        r = r.reshape(aa[0].shape)
        return float(r) if r.ndim == 0 else r
    return f


def _sfun(f):
    def g(ev, *vals):
        if any(isinstance(v, np.ndarray) for v in vals):
            n = max(len(v) for v in vals if isinstance(v, np.ndarray))
            cols = [v if isinstance(v, np.ndarray) else [v] * n for v in vals]
            out = [f(*row) for row in zip(*cols)]
            if out and isinstance(out[0], str):
                return np.array(out, dtype=object)
            return np.array(out, dtype=np.float64)
        return f(*vals)
    return g


def _substr(s, a, b=M.SYSMISS):
    n = len(s)
    a = int(a)
    if a < 0:
        a = n + a + 1
    if a < 1 or a > n:
        return ""
    if b >= M.SYSMISS:
        return s[a - 1:]
    return s[a - 1:a - 1 + max(int(b), 0)]


def _real(s):
    try:
        return float(s.strip()) if s.strip() not in ("", ".") else M.SYSMISS
    except ValueError:
        return M.SYSMISS


def _string(x, f=None):
    from .fmt import fmt_num, gnum
    if f is None:
        return gnum(x, 9) if x < M.SYSMISS else M.missing_label(x)
    return fmt_num(x, f).strip()


def _word(s, n):
    w = s.split()
    n = int(n)
    if n < 0:
        n = len(w) + n + 1
    return w[n - 1] if 1 <= n <= len(w) else ""


def _sum(ev, x):
    a = np.asarray(x, dtype=np.float64)
    a = np.where(a >= M.SYSMISS, 0.0, a)
    if ev.byn is not None and ev.groups is not None:
        out = np.empty_like(a)
        for s, e in ev.groups:
            out[s:e] = np.cumsum(a[s:e])
        return out
    return np.cumsum(a)


def _normal(ev, x):
    from scipy.special import ndtr
    return _vec(ndtr, x)


def _invnormal(ev, x):
    from scipy.special import ndtri
    return _vec(lambda a: np.where((a <= 0) | (a >= 1), np.nan, ndtri(np.clip(a, 1e-300, 1 - 1e-16))), x)


def _int(a):
    return np.trunc(a)


FUNCS = {
    "abs": lambda ev, x: _vec(np.abs, x),
    "ln": lambda ev, x: _vec(lambda a: np.where(a > 0, np.log(np.where(a > 0, a, 1)), np.nan), x),
    "log": lambda ev, x: _vec(lambda a: np.where(a > 0, np.log(np.where(a > 0, a, 1)), np.nan), x),
    "log10": lambda ev, x: _vec(lambda a: np.where(a > 0, np.log10(np.where(a > 0, a, 1)), np.nan), x),
    "exp": lambda ev, x: _vec(np.exp, x),
    "sqrt": lambda ev, x: _vec(lambda a: np.where(a >= 0, np.sqrt(np.abs(a)), np.nan), x),
    "int": lambda ev, x: _vec(_int, x),
    "trunc": lambda ev, x: _vec(_int, x),
    "floor": lambda ev, x: _vec(np.floor, x),
    "ceil": lambda ev, x: _vec(np.ceil, x),
    "round": _round,
    "mod": lambda ev, x, y: _vec(lambda a, b: np.where(b == 0, np.nan, a - b * np.floor(a / np.where(b == 0, 1, b))), x, y),
    "sign": lambda ev, x: _vec(np.sign, x),
    "min": _rowfn("min"),
    "max": _rowfn("max"),
    "missing": _missing,
    "mi": _missing,
    "inlist": _inlist,
    "inrange": _inrange,
    "cond": _cond,
    "sum": _sum,
    "normal": _normal,
    "invnormal": _invnormal,
    "logit": lambda ev, x: _vec(lambda a: np.log(a / (1 - a)), x),
    "invlogit": lambda ev, x: _vec(lambda a: 1 / (1 + np.exp(-a)), x),
    "substr": _sfun(_substr),
    "usubstr": _sfun(_substr),
    "strlen": _sfun(lambda s: float(len(s.encode("utf-8")))),
    "length": _sfun(lambda s: float(len(s.encode("utf-8")))),
    "ustrlen": _sfun(lambda s: float(len(s))),
    "upper": _sfun(lambda s: s.upper()),
    "strupper": _sfun(lambda s: s.upper()),
    "lower": _sfun(lambda s: s.lower()),
    "strlower": _sfun(lambda s: s.lower()),
    "trim": _sfun(lambda s: s.strip(" ")),
    "strtrim": _sfun(lambda s: s.strip(" ")),
    "ltrim": _sfun(lambda s: s.lstrip(" ")),
    "rtrim": _sfun(lambda s: s.rstrip(" ")),
    "itrim": _sfun(lambda s: re.sub(" +", " ", s)),
    "stritrim": _sfun(lambda s: re.sub(" +", " ", s)),
    "strpos": _sfun(lambda s, t: float(s.find(t) + 1)),
    "subinstr": _sfun(lambda s, a, b, n: s.replace(a, b) if n >= M.SYSMISS else s.replace(a, b, int(n))),
    "real": _sfun(_real),
    "string": _sfun(_string),
    "strofreal": _sfun(_string),
    "word": _sfun(_word),
    "wordcount": _sfun(lambda s: float(len(s.split()))),
    "regexm": _sfun(lambda s, p: float(re.search(p, s) is not None)),
}
LAZY = {"cond"}
