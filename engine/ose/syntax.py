"""Split a command's arguments into the standard parts.

    [varlist | =exp] [if exp] [in range] [weight] [using filename] [, options]

Splitting respects quotes, compound quotes, parentheses and brackets.
"""
import re

from .errors import StataError


def scan(s):
    """Yield (index, char, depth, inquote) for top-level scanning."""
    depth = 0
    q = None
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if q == '"':
            if c == '"':
                q = None
            yield i, c, depth, True
            i += 1
            continue
        if q == "`\"":
            if s.startswith("\"'", i):
                q = None
                yield i, c, depth, True
                i += 2
                continue
            yield i, c, depth, True
            i += 1
            continue
        if s.startswith('`"', i):
            q = "`\""
            yield i, c, depth, True
            i += 2
            continue
        if c == '"':
            q = '"'
            yield i, c, depth, True
            i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        yield i, c, depth, False
        i += 1


def split_top(s, sep=","):
    """Split at the first top-level occurrence of sep. Returns (before, after|None)."""
    for i, c, d, q in scan(s):
        if not q and d == 0 and c == sep:
            return s[:i], s[i + 1:]
    return s, None


def find_keyword(s, kw):
    """Index of a top-level keyword (whole word), or -1."""
    pat = re.compile(r"(?<![A-Za-z0-9_.`'$])" + kw + r"(?![A-Za-z0-9_])")
    state = {j: (d, q) for j, c, d, q in scan(s)}
    for m in pat.finditer(s):
        d, q = state.get(m.start(), (1, True))
        if d == 0 and not q:
            return m.start()
    return -1


def unquote(s):
    s = s.strip()
    if s.startswith('`"') and s.endswith("\"'"):
        return s[2:-2]
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


class Parsed:
    def __init__(self):
        self.varlist = ""     # text before if/in/using/weight
        self.exp = None       # text after '=' for =exp commands
        self.if_ = None
        self.in_ = None
        self.weight = None    # (kind, exp)
        self.using = None
        self.options = {}     # name -> argument text (or True)
        self.opt_text = ""


def parse_standard(args, using=True):
    p = Parsed()
    main, opts = split_top(args, ",")
    p.opt_text = opts or ""
    p.options = parse_options(opts or "")
    # weight in [] at top level
    w = None
    for i, c, d, q in scan(main):
        if c == "[" and d == 1 and not q:
            j = _match(main, i)
            inner = main[i + 1:j].strip()
            m = re.match(r"^(fweight|fw|aweight|aw|pweight|pw|iweight|iw|weight)\s*=\s*(.+)$", inner)
            if m:
                w = (m.group(1), m.group(2))
                main = main[:i] + " " + main[j + 1:]
                break
    p.weight = w
    if using:
        k = find_keyword(main, "using")
        if k >= 0:
            rest = main[k + 5:]
            main = main[:k]
            p.using = _take_filename(rest)
    ki = find_keyword(main, "in")
    kf = find_keyword(main, "if")
    cuts = sorted(x for x in (ki, kf) if x >= 0)
    head = main[:cuts[0]] if cuts else main
    for idx, c in enumerate(cuts):
        end = cuts[idx + 1] if idx + 1 < len(cuts) else len(main)
        seg = main[c:end]
        if c == kf:
            p.if_ = seg[2:].strip()
        else:
            p.in_ = seg[2:].strip()
    head = head.strip()
    eq = None
    for i, c, d, q in scan(head):
        if c == "=" and d == 0 and not q:
            prev = head[i - 1] if i else ""
            nxt = head[i + 1] if i + 1 < len(head) else ""
            if prev not in "=!<>~" and nxt != "=":
                eq = i
                break
    if eq is not None:
        p.varlist = head[:eq].strip()
        p.exp = head[eq + 1:].strip()
    else:
        p.varlist = head
    return p


def _take_filename(rest):
    rest = rest.strip()
    if rest.startswith('"'):
        j = rest.find('"', 1)
        return rest[1:j]
    if rest.startswith('`"'):
        j = rest.find("\"'", 2)
        return rest[2:j]
    return rest.split()[0] if rest else ""


def _match(s, i):
    depth = 0
    for j, c, d, q in scan(s[i:]):
        if not q and c in "([{":
            depth += 1
        elif not q and c in ")]}":
            depth -= 1
            if depth == 0:
                return i + j
    raise StataError("unmatched bracket", 198)


def parse_options(s):
    """Parse 'a b(c) d( e f )' into {'a': True, 'b': 'c', 'd': ' e f '}."""
    out = {}
    s = s.strip()
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        m = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", s[i:])
        if not m:
            raise StataError(f"option {s[i:].split()[0]} not allowed", 198)
        name = m.group(0)
        i += len(name)
        if i < n and s[i] == "(":
            j = _match(s, i)
            out[name] = s[i + 1:j]
            i = j + 1
        else:
            out[name] = True
    return out


def opt_lookup(options, spec):
    """Match user options against a spec like 'Detail SEParator() MEANonly'.

    Capital letters mark the shortest accepted abbreviation. Returns dict
    canonical-lowercase-name -> value. Unknown options raise.
    """
    specs = []
    for item in spec.split():
        arg = item.endswith("()")
        item = item[:-2] if arg else item
        k = 0
        while k < len(item) and item[k].isupper():
            k += 1
        k = max(k, 1) if any(ch.isupper() for ch in item) else len(item)
        specs.append((item.lower(), k, arg))
    out = {}
    for name, val in options.items():
        low = name.lower()
        hit = None
        for full, k, arg in specs:
            if full.startswith(low) and len(low) >= k:
                hit = (full, arg)
                break
            if full.startswith("no") is False and low.startswith("no") and full.startswith(low[2:]) and len(low) - 2 >= k:
                hit = ("no" + full, arg)
                break
        if hit is None:
            raise StataError(f"option {name} not allowed", 198)
        out[hit[0]] = val
    return out
