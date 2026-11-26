"""Session, macro, logging and display commands."""
import os
import re
import time

import numpy as np

from .. import missing as M
from .. import expr as X
from ..errors import ExitDo, StataError, Unsupported
from ..fmt import fmt_num, gnum
from ..interp import Log, command
from ..syntax import parse_options, parse_standard, split_top, unquote

DASHES = "-" * 79


def path_of(it, name):
    name = unquote(name)
    return name if os.path.isabs(name) else os.path.join(it.cwd, name)


@command("version", 3)
def cmd_version(it, rest):
    if ":" in rest:
        it.dispatch(rest.split(":", 1)[1].strip())


@command("set")
def cmd_set(it, rest):
    parts = rest.split()
    if not parts:
        raise StataError("invalid syntax", 198)
    key = parts[0]
    val = " ".join(parts[1:])
    known = {"more", "varabbrev", "type", "seed", "linesize", "matsize", "maxvar", "memory", "trace",
             "output", "rmsg", "scheme", "graphics", "emptycells", "sortseed", "dp", "niceness", "segmentsize",
             "processors", "maxiter", "logtype", "fvlabel", "showbaselevels", "cformat", "pformat", "sformat",
             "level", "printcolor", "copycolor", "autotabgraphs", "fvwrap", "pagesize", "tracedepth", "obs",
             "excelxlsxlargefile", "charset", "locale_functions", "max_memory", "min_memory", "include_bitmap"}
    if key == "obs":
        n = int(float(val.split(",")[0]))
        it.ds.set_obs(n)
        return
    if key == "seed":
        it.settings["seed"] = val
        return
    if key not in known:
        raise Unsupported(f"set {key}")
    it.settings[key] = val.split(",")[0].strip()
    if key == "varabbrev":
        it.ds.varabbrev = it.settings[key] == "on"
    if key == "type":
        it.settings["type"] = val.split(",")[0].strip()


@command("clear")
def cmd_clear(it, rest):
    keep_abbrev = it.ds.varabbrev
    from ..dataset import Dataset
    it.ds = Dataset()
    it.ds.varabbrev = keep_abbrev
    if rest.strip() in ("all", "*"):
        it.scalars.clear()
        it.estimates.clear()
        it.e = {}
        it.r = {}


@command("macro", 3)
def cmd_macro(it, rest):
    w = rest.split()
    if w and w[0] in ("drop", "dir", "list"):
        if w[0] == "drop":
            for n in w[1:]:
                if n == "_all":
                    it.globals.clear()
                else:
                    it.globals.pop(n.lstrip("_"), None) if not n.startswith("_") else it.locals.pop(n[1:], None)
        return
    raise Unsupported(f"macro {rest}")


def _assign_macro(it, store, rest, kind):
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", rest, re.S)
    if not m:
        raise StataError("invalid syntax", 198)
    name, val = m.group(1), m.group(2)
    name = name[:31] if kind == "local" else name[:32]
    if val.startswith("="):
        v = it.eval_scalar_expr(val[1:])
        store[name] = v if isinstance(v, str) else it.num_to_macro(v)
    elif val.startswith(":"):
        store[name] = it.extended_function(val[1:].strip())
    elif val.startswith("++") or val.startswith("--"):
        raise Unsupported("local ++")
    else:
        val = val.strip() if not val.startswith(" ") else val.strip()
        if val.startswith('`"') and val.endswith("\"'"):
            val = val[2:-2]
        elif len(val) >= 2 and val[0] == '"' and val[-1] == '"' and val.count('"') == 2:
            val = val[1:-1]
        store[name] = val


@command("local", 3)
def cmd_local(it, rest):
    _assign_macro(it, it.locals, rest, "local")


@command("global", 2)
def cmd_global(it, rest):
    _assign_macro(it, it.globals, rest, "global")


@command("scalar", 2)
def cmd_scalar(it, rest):
    m = re.match(r"^(?:define\s+)?([A-Za-z_]\w*)\s*=\s*(.+)$", rest, re.S)
    if not m:
        w = rest.split()
        if w and w[0] == "drop":
            for n in w[1:]:
                it.scalars.pop(n, None) if n != "_all" else it.scalars.clear()
            return
        raise Unsupported(f"scalar {rest}")
    it.scalars[m.group(1)] = it.eval_scalar_expr(m.group(2))


@command("tempvar")
def cmd_tempvar(it, rest):
    for n in rest.split():
        it._tmp = getattr(it, "_tmp", 0) + 1
        it.locals[n] = f"__{it._tmp:06d}"


@command("tempname")
def cmd_tempname(it, rest):
    cmd_tempvar(it, rest)


@command("tempfile")
def cmd_tempfile(it, rest):
    import tempfile
    for n in rest.split():
        fd, p = tempfile.mkstemp(prefix="ose", suffix=".tmp")
        os.close(fd)
        os.unlink(p)
        it.locals[n] = p
        it.tempfiles.add(p)


@command("mkdir")
def cmd_mkdir(it, rest):
    main, opts = split_top(rest, ",")
    p = path_of(it, main.strip())
    if os.path.isdir(p):
        raise StataError(f"could not create directory {unquote(main.strip())}", 693)
    os.makedirs(p) if opts else os.mkdir(p)


@command("cd")
def cmd_cd(it, rest):
    if not rest.strip():
        it.print(it.cwd)
        return
    p = path_of(it, rest.strip())
    if not os.path.isdir(p):
        raise StataError(f"unable to change to {unquote(rest.strip())}", 170)
    it.cwd = os.path.normpath(p)
    it.print(it.cwd)


@command("pwd")
def cmd_pwd(it, rest):
    it.print(it.cwd)


@command("exit")
def cmd_exit(it, rest):
    raise ExitDo()


@command("more")
def cmd_more(it, rest):
    pass


@command("discard")
def cmd_discard(it, rest):
    pass


@command("timer")
def cmd_timer(it, rest):
    pass


@command("log")
def cmd_log(it, rest):
    w = rest.split(None, 1)
    sub = w[0] if w else ""
    arg = w[1] if len(w) > 1 else ""
    if sub == "using":
        main, opts = split_top(arg, ",")
        o = parse_options(opts or "")
        fname = unquote(main.strip())
        kind = "text" if ("text" in o or fname.endswith(".log")) else "smcl"
        if not os.path.splitext(fname)[1]:
            fname += ".log" if kind == "text" else ".smcl"
        if kind != "text":
            raise Unsupported("smcl log output")
        name = o.get("name", "<unnamed>")
        name = name if name is not True else "<unnamed>"
        p = path_of(it, fname)
        if os.path.exists(p) and "replace" not in o and "append" not in o:
            raise StataError(f"file {fname} already exists", 602)
        if any(lg.name == name for lg in it.logs):
            raise StataError(f"log file already open", 604)
        try:
            lg = Log(p, name, kind, append="append" in o)
        except OSError:
            why = " (append reads the file's last byte, so the file must be readable and writable)" if "append" in o \
                else ""
            raise StataError(f"ose: could not open log {fname}{why}", 603) from None
        it.logs.append(lg)
        hdr = [DASHES, f"      name:  {name}", f"       log:  {os.path.abspath(p)}", f"  log type:  {kind}",
               f" opened on:  {_now()}"]
        for h in hdr:
            it._emit(h)
        it._last_printed = True
        return
    if sub == "close":
        name = arg.strip() or None
        if name in ("_all",):
            targets = list(it.logs)
        elif name:
            targets = [lg for lg in it.logs if lg.name == name]
            if not targets:
                raise StataError(f"log file {name} not open", 111) if it.logs else StataError("no log file open", 606)
        else:
            targets = [lg for lg in it.logs if lg.name == "<unnamed>"] or it.logs[:1]
            if not targets:
                raise StataError("no log file open", 606)
        for lg in targets:
            ftr = [f"      name:  {lg.name}", f"       log:  {os.path.abspath(lg.path)}", f"  log type:  {lg.kind}",
                   f" closed on:  {_now()}", DASHES]
            for h in ftr:
                it._emit(h)
            lg.f.close()
            it.logs.remove(lg)
        return
    if sub in ("off", "on", "query"):
        return
    raise Unsupported(f"log {sub}")


def _now():
    return time.strftime("%d %b %Y, %H:%M:%S").lstrip("0")


@command("display", 2)
def cmd_display(it, rest):
    it.print(display_text(it, rest))


def display_text(it, s):
    """Evaluate the display directive list."""
    out = []
    i = 0
    s = s.strip()
    fmt = None
    col = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if s.startswith('`"', i):
            j = s.find("\"'", i + 2)
            out.append(s[i + 2:j])
            i = j + 2
            continue
        if c == '"':
            j = s.find('"', i + 1)
            if j < 0:
                raise StataError("invalid syntax", 198)
            out.append(s[i + 1:j])
            i = j + 1
            continue
        if c == "_":
            m = re.match(r"_(skip|col|column|newline|n|dup)\s*\(\s*(\d+)\s*\)|_(newline|n)\b", s[i:])
            if m:
                kind = m.group(1) or m.group(3)
                k = int(m.group(2)) if m.group(2) else 1
                cur = "".join(out)
                if kind == "skip":
                    out.append(" " * k)
                elif kind in ("col", "column"):
                    last = cur.split("\n")[-1]
                    out.append(" " * max(k - 1 - len(last), 0))
                elif kind in ("newline", "n"):
                    out.append("\n" * k)
                i += m.end()
                continue
        if c == "%":
            m = re.match(r"%-?\d*\.?\d*[gfes]c?", s[i:])
            if m:
                fmt = m.group(0)
                i += m.end()
                continue
        if s.startswith("as ", i) or s.startswith("in ", i):
            m = re.match(r"(as|in)\s+(text|txt|result|res|error|err|input|inp|smcl)\b", s[i:])
            if m:
                i += m.end()
                continue
        # an expression: take up to the next top-level space-separated chunk that parses
        j = _expr_end(s, i)
        e = s[i:j]
        v = it.eval_scalar_expr(e)
        if isinstance(v, str):
            out.append(v)
        else:
            out.append(fmt_num(v, fmt).lstrip() if fmt and not fmt.endswith("s") else (gnum(v, 10) if v < M.SYSMISS else M.missing_label(v)))
            if fmt:
                out[-1] = fmt_num(v, fmt)
        fmt = None
        i = j
    return "".join(out)


def _expr_end(s, i):
    """Find the end of an expression starting at i in a display list."""
    best = None
    depth = 0
    q = False
    j = i
    while j <= len(s):
        if j == len(s) or (s[j] == " " and depth == 0 and not q):
            cand = s[i:j]
            try:
                X.parse(cand)
                best = j
            except Exception:
                pass
        if j < len(s):
            ch = s[j]
            if ch == '"':
                q = not q
            elif not q and ch in "([":
                depth += 1
            elif not q and ch in ")]":
                depth -= 1
        j += 1
    if best is None:
        raise StataError("invalid syntax", 198)
    return best


@command("return")
def cmd_return(it, rest):
    raise Unsupported("return")


@command("which")
def cmd_which(it, rest):
    raise Unsupported("which")


@command("ssc")
def cmd_ssc(it, rest):
    raise Unsupported("ssc (package installation)")


@command("net")
def cmd_net(it, rest):
    raise Unsupported("net (package installation)")


@command("do")
def cmd_do(it, rest):
    p = path_of(it, rest.strip().split(",")[0])
    if not os.path.splitext(p)[1]:
        p += ".do"
    if not os.path.exists(p):
        raise StataError(f"file {rest.strip()} not found", 601)
    it.frames.append({})
    try:
        it.run_file(p)
    finally:
        it.frames.pop()
    it.print("")
    it.print("end of do-file")


@command("run")
def cmd_run(it, rest):
    q = it.quiet
    it.quiet = q + 1
    try:
        cmd_do(it, rest)
    finally:
        it.quiet = q
