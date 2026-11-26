"""The interpreter: runs logical lines, handles blocks, prefixes and output."""
import os
import re
import time

import numpy as np

from . import missing as M
from .dataset import Dataset
from .errors import ExitDo, StataError, Unsupported
from .lexer import Line, logical_lines
from .macro import MacroExpander
from . import expr as X
from .syntax import split_top

LINESIZE = 80
REGISTRY = {}   # full name -> (minlen, handler)


def command(name, minlen=None, raw=False):
    """Register a command. minlen is the shortest accepted abbreviation."""
    def deco(fn):
        REGISTRY[name] = (minlen or len(name), fn, raw)
        return fn
    return deco


def lookup(word):
    if word in REGISTRY:
        return REGISTRY[word]
    hits = [v for k, v in REGISTRY.items() if k.startswith(word) and len(word) >= v[0]]
    if len(hits) == 1:
        return hits[0]
    return None


class Log:
    def __init__(self, path, name, kind, append=False):
        self.path = path
        self.name = name
        self.kind = kind
        # `append` adds a new session after the file's existing text; anything else starts the file again.
        # A nonempty file whose last byte ends no line gets one line end first, so its last line stays as it was and
        # the new header starts a line of its own. The existing bytes are never changed. The last byte is read from
        # the same open file the session is appended to, so append needs a file the caller can read as well as write;
        # an OSError here (a write-only file, for one) is a file-access failure that `log using` reports.
        if not append:
            self.f = open(path, "w", encoding="utf-8")
            return
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
        try:
            size = os.fstat(fd).st_size
            sep = False
            if size:
                os.lseek(fd, size - 1, os.SEEK_SET)
                sep = os.read(fd, 1) not in (b"\n", b"\r")
            self.f = open(fd, "a", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        if sep:
            self.f.write("\n")


class Block:
    """A braced block: header line, body (lines/blocks), closing line."""

    def __init__(self, head, body, close):
        self.head = head
        self.body = body
        self.close = close


class Interp:
    def __init__(self, cwd=None, out=None):
        self.ds = Dataset()
        self.globals = {"S_ADO": "BASE;SITE;.;PERSONAL;PLUS;OLDPLACE"}
        self.frames = [{}]
        self.scalars = {}
        self.rc = 0
        self.r = {}
        self.e = {}
        self.logs = []
        self.quiet = 0
        self.cwd = cwd or os.getcwd()
        self.transcript = out
        self.macro = MacroExpander(self)
        self.programs = {}
        self.estimates = {}
        self.tempfiles = set()   # paths handed out by `tempfile` (save prints a not-found note for these)
        self.settings = {"more": "off", "varabbrev": "on", "type": "float", "seed": "", "linesize": "80"}
        self.capture_depth = 0
        self.unsupported = []
        self.preserved = None
        self.by = None
        self._else_pending = False

    # --- macros and scalar helpers ------------------------------------------
    @property
    def locals(self):
        return self.frames[-1]

    def num_to_macro(self, v):
        if isinstance(v, str):
            return v
        if v >= M.SYSMISS:
            return M.missing_label(v)
        if float(v).is_integer() and abs(v) < 1e15:
            return str(int(v))
        s = repr(float(v))
        if "e" in s:
            m, e = s.split("e")
            s = f"{m}e{e[0] if e[0] in '+-' else '+'}{int(e.lstrip('+-')):02d}"
        from .fmt import lead
        return lead(s)

    def eval_scalar_expr(self, text):
        node = X.parse(text.strip())
        ev = X.Evaluator(self)
        ev.scalar = True
        ev.rows = np.array([0]) if self.ds.N else np.array([], dtype=np.int64)
        v = ev.eval(node)
        if isinstance(v, np.ndarray):
            if v.size == 0:
                return M.SYSMISS if v.dtype != object else ""
            v = v[0]
            v = str(v) if isinstance(v, str) else float(v)
        return v

    def extended_function(self, text):
        from .commands.macrofns import extended
        return extended(self, text)

    def result_value(self, kind, name):
        if kind == "c":
            from .commands.macrofns import cvalue
            return cvalue(self, name)
        d = {"r": self.r, "e": self.e, "s": {}}[kind]
        v = d.get(name)
        if v is None:
            return M.SYSMISS
        if isinstance(v, str):
            return v
        if isinstance(v, np.ndarray):
            raise StataError("matrix operators that return matrices not allowed in this context", 509)
        return float(v)

    def coef_value(self, kind, inner):
        b = self.e.get("_b")
        if b is None:
            raise StataError("last estimates not found", 301)
        names = self.e.get("_colnames", [])
        key = inner.strip()
        if key not in names:
            raise StataError(f"[{key}] not found", 111)
        j = names.index(key)
        if kind in ("_b", "_coef"):
            return float(b[j])
        V = self.e.get("V")
        return float(np.sqrt(V[j, j]))

    # --- output ------------------------------------------------------------
    def out(self, text="", force=False):
        if self.quiet and not force:
            return
        self._emit(text)

    def _emit(self, text):
        for lg in self.logs:
            lg.f.write(text + "\n")
        if self.transcript is not None:
            self.transcript.write(text + "\n")

    def echo(self, line, prefix=". "):
        if self.quiet:
            return
        for k, raw in enumerate(line.raw):
            raw = raw.expandtabs(8)
            first = (prefix if k == 0 else "> ") + raw
            self._emit_wrapped(first)

    def linesize(self):
        try:
            return int(float(self.settings.get("linesize", LINESIZE)))
        except ValueError:
            return LINESIZE

    def _emit_wrapped(self, s):
        width = self.linesize() - 1  # HNPXO1 wraps at 79 (linesize 80); 3EDO2Y at 104 (linesize 105)
        if len(s) <= width:
            t = s.rstrip()
            # An empty echo line keeps its prefix as logs print it: ". " and "> " (a `///` before a blank line).
            self._emit(t + " " if t in (".", ">") and s.startswith(t + " ") else t)
            return
        self._emit(s[:width])
        rest = s[width:]
        while rest:
            chunk = "> " + rest[:width - 2]
            rest = rest[width - 2:]
            self._emit(chunk)

    # --- running -------------------------------------------------------------
    def run_file(self, path, echo=True):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        lines = logical_lines(text)
        tree = build_tree(lines)
        before = self.preserved
        try:
            self.run_tree(tree, echo=echo)
        except ExitDo:
            pass
        except StataError as e:
            if isinstance(e, Unsupported):
                self.unsupported.append(e.what)
            self.error(e)
            self._emit("")
            self._emit("end of do-file")
            raise
        finally:
            if self.preserved is not None and self.preserved is not before:
                self.ds = self.preserved  # data preserved in this do-file come back when it ends
                self.preserved = before

    def run_tree(self, items, echo=True):
        for item in items:
            if isinstance(item, Block):
                if echo:
                    self.echo_block(item)
                self.exec_block(item)
            else:
                if echo:
                    self.echo(item)
                if item.text.strip():
                    try:
                        self.exec_line(item.text)
                    except Unsupported as e:
                        if e.cmd is None:  # raised before dispatch (macro expansion): name the line's command
                            w = re.match(r"\s*([A-Za-z_]\w*)", item.text)
                            e.cmd = w.group(1) if w else None
                        raise
                if echo and not self.quiet and item.text.strip() and getattr(self, "_printed", True):
                    pass
                if echo:
                    self._after_command(item)

    def _after_command(self, item):
        # The log shows a blank line after the output of any command that
        # printed something; commands printing nothing are followed by none.
        if self._last_printed and not self.quiet:
            self._emit("")
        self._last_printed = False

    _last_printed = False

    def echo_block(self, block):
        if self.quiet:
            return
        self.echo(block.head)
        n = [1]

        def walk(items):
            for it in items:
                if isinstance(it, Block):
                    n[0] += 1
                    self.echo(it.head, prefix=f"{n[0]:>3}. ")
                    walk(it.body)
                    n[0] += 1
                    self.echo(it.close, prefix=f"{n[0]:>3}. ")
                else:
                    n[0] += 1
                    self.echo(it, prefix=f"{n[0]:>3}. ")
        walk(block.body)
        n[0] += 1
        self.echo(block.close, prefix=f"{n[0]:>3}. ")

    def exec_block(self, block):
        from .commands.control import run_block
        run_block(self, block)

    def exec_line(self, text, expand=True):
        if expand:
            text = self.macro.expand(text)
        text = text.strip()
        if not text:
            return
        self.dispatch(text)

    def dispatch(self, text):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(:?)(.*)$", text, re.S)
        if not m:
            if text.startswith("#delimit"):
                return
            if text.lstrip().startswith("!"):
                e = Unsupported("shell escape (the engine never runs other programs)")
                e.cmd = "shell"
                raise e
            raise StataError(f"{text.split()[0]} is not a valid command name", 199)
        word, colon, rest = m.group(1), m.group(2), m.group(3)
        if colon and word not in ("by", "bysort", "bys"):
            rest = ":" + rest
        prefix = PREFIXES.get(word) or next((v for k, v in PREFIX_ABBR.items() if word.startswith(k) and v[1].startswith(word)), None)
        if prefix:
            return prefix[0](self, rest.strip())
        hit = lookup(word)
        if hit is None:
            # Could be a built-in we lack or a user-written command: we cannot tell, so never continue.
            e = Unsupported(f"command {word}")
            e.cmd = word
            raise e
        minlen, fn, raw = hit
        try:
            fn(self, rest.strip())
        except Unsupported as e:
            if e.cmd is None:
                e.cmd = word
            raise
        except StataError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:  # a bug in the engine: fail loudly, never guess
            raise StataError(f"ose: internal error in {word}: {type(e).__name__}: {e}", 9999)

    def print(self, text=""):
        """Command output. Marks that the command printed something."""
        if self.quiet:
            return
        self._last_printed = True
        self._emit(text)

    def print_wrapped(self, text):
        """Command output longer than the line: wrapped at linesize-1 with '> ' continuations, as logs show."""
        if self.quiet:
            return
        self._last_printed = True
        self._emit_wrapped(text)

    def error(self, err):
        self.print(err.msg) if err.msg else None
        self.print(f"r({err.rc});")


# --- prefixes ------------------------------------------------------------------

def _capture(it, rest):
    it.quiet += 1
    it.capture_depth += 1
    try:
        if rest.strip() == "{":
            raise Unsupported("capture { block on one line")
        it.dispatch(rest)
        it.rc = 0
    except Unsupported:
        # Never swallow: the authors' run executed this command; continuing would guess at state.
        raise
    except StataError as e:
        it.rc = e.rc
    finally:
        it.quiet -= 1
        it.capture_depth -= 1


def _quietly(it, rest):
    it.quiet += 1
    try:
        it.dispatch(rest)
    finally:
        it.quiet -= 1


def _noisily(it, rest):
    q = it.quiet
    it.quiet = 0
    try:
        it.dispatch(rest)
    finally:
        it.quiet = q


def _by(it, rest, sort=False):
    from .commands.byprefix import run_by
    return run_by(it, rest, sort)


PREFIXES = {
    "capture": (_capture, "capture"), "cap": (_capture, "capture"), "capt": (_capture, "capture"),
    "quietly": (_quietly, "quietly"), "qui": (_quietly, "quietly"), "quietl": (_quietly, "quietly"),
    "noisily": (_noisily, "noisily"), "noi": (_noisily, "noisily"),
    "by": (lambda it, r: _by(it, r, False), "by"),
    "bysort": (lambda it, r: _by(it, r, True), "bysort"), "bys": (lambda it, r: _by(it, r, True), "bysort"),
}
PREFIX_ABBR = {"capt": (_capture, "capture"), "qui": (_quietly, "quietly"), "noi": (_noisily, "noisily"),
               "bys": (lambda it, r: _by(it, r, True), "bysort")}


# --- block structure ------------------------------------------------------------

def opens_block(text):
    t = text.rstrip()
    return t.endswith("{") and not t.endswith("${")


def build_tree(lines):
    """Group lines into Blocks by braces. A line ending in '{' opens one."""
    root = []
    stack = [(None, root)]
    for ln in lines:
        t = ln.text.strip()
        if t == "}" or (t.startswith("}") and stack[-1][0] is not None and not t.startswith("}else")
                        and not re.match(r"^\}\s*else", t)):
            if len(stack) == 1:
                root.append(ln)
                continue
            head, body = stack.pop()
            blk = Block(head, body, ln)
            stack[-1][1].append(blk)
            continue
        m = re.match(r"^\}\s*(else.*)$", t)
        if m and len(stack) > 1:
            head, body = stack.pop()
            stack[-1][1].append(Block(head, body, Line(ln.raw, "}", ln.lineno)))
            nl = Line(ln.raw, m.group(1), ln.lineno)
            if opens_block(nl.text):
                stack.append((nl, []))
            else:
                stack[-1][1].append(nl)
            continue
        if opens_block(t) and not t.startswith("*"):
            stack.append((ln, []))
            continue
        stack[-1][1].append(ln)
    while len(stack) > 1:
        head, body = stack.pop()
        stack[-1][1].append(Block(head, body, Line([""], "}", 0)))
    return root
