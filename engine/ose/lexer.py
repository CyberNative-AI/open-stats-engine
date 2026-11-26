"""Turn do-file text into logical command lines.

Each logical line keeps its raw physical lines (for the echo in the log) and
a cleaned text with comments removed and `///` continuations joined.
"""
import re


class Line:
    __slots__ = ("raw", "text", "lineno")

    def __init__(self, raw, text, lineno):
        self.raw = raw          # list of physical lines, as typed
        self.text = text        # cleaned command text
        self.lineno = lineno

    def __repr__(self):
        return f"Line({self.lineno}: {self.text!r})"


def _strip_comments(s, state):
    """Remove /* */ and // comments from one physical line.

    state['block'] carries an open /* comment across lines. Returns
    (text, continued) where continued is True if the line ended in ///.
    """
    out = []
    i = 0
    n = len(s)
    quote = None
    while i < n:
        if state["block"]:
            j = s.find("*/", i)
            k = s.find("/*", i)
            if k != -1 and (j == -1 or k < j):
                state["block"] += 1
                i = k + 2
                continue
            if j == -1:
                return "".join(out), False
            state["block"] -= 1
            i = j + 2
            continue
        c = s[i]
        if quote:
            out.append(c)
            if quote == '"' and c == '"':
                quote = None
            elif quote == "`\"" and s.startswith("\"'", i):
                out.append("'")
                i += 2
                quote = None
                continue
            i += 1
            continue
        if c == "`" and s.startswith('`"', i):
            quote = "`\""
            out.append('`"')
            i += 2
            continue
        if c == '"':
            quote = '"'
            out.append(c)
            i += 1
            continue
        if s.startswith("/*", i):
            state["block"] += 1
            i += 2
            continue
        if s.startswith("///", i) and (i == 0 or s[i - 1] in " \t"):
            return "".join(out), True
        if s.startswith("//", i) and (i == 0 or s[i - 1] in " \t"):
            return "".join(out), False
        out.append(c)
        i += 1
    return "".join(out), False


def logical_lines(text):
    """Split do-file text into Line objects (handles #delimit ;)."""
    phys = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = []
    state = {"block": 0}
    delim_semicolon = False
    star_comment = False
    buf_raw, buf_txt, start = [], [], None
    for no, p in enumerate(phys, 1):
        stripped = p.strip()
        if not buf_raw and not state["block"]:
            m = re.match(r"^#\s*d(e(l(i(m(i(t)?)?)?)?)?)?\s+(\S+)", stripped)
            if m:
                delim_semicolon = m.group(7) == ";"
                lines.append(Line([p], "#delimit " + m.group(7), no))
                continue
            if stripped.startswith("*") and not delim_semicolon:
                lines.append(Line([p], "", no))
                continue
        was_block = state["block"] > 0
        saved_state = dict(state)
        txt, cont = _strip_comments(p, state)
        if start is None:
            start = no
        buf_raw.append(p)
        if delim_semicolon:
            # In ";" mode a statement whose first non-blank character is "*" is a comment
            # that runs to the next semicolon, across lines (doi:10.7910/DVN/R7RYIV table6and7.do).
            if not star_comment and not was_block and txt.strip().startswith("*") \
                    and all(not t.strip() for t in buf_txt):
                star_comment = True
                while len(buf_raw) > 1 and not buf_raw[0].strip():
                    buf_raw.pop(0)  # the echo starts at the comment, not at blank lines before it
                start = no
            if star_comment:
                state.clear()
                state.update(saved_state)  # comment text is not scanned for /* or quotes
                if ";" not in p:
                    continue
                star_comment = False
                lines.append(Line(buf_raw, "", start))
                rest = p.split(";", 1)[1]
                buf_raw, buf_txt, start = [], [], None
                if not rest.strip():
                    continue
                txt, _ = _strip_comments(rest, state)
                start = no
                p = rest
                buf_raw = [rest]
            parts = txt.split(";")
            # Text after the last ";" on this line opens the next statement's echo, as the authors'
            # log shows (". /* comment */" then "> replace ..."; doi:10.7910/DVN/R7RYIV table6and7).
            # Only when every ";" in the raw line is a real separator; otherwise the echo drops it.
            exact = len(parts) > 1 and p.count(";") == len(parts) - 1
            tail = p[p.rfind(";") + 1:] if exact else ""
            if exact and buf_raw and buf_raw[-1] is p:
                buf_raw[-1] = p[:p.find(";") + 1]  # the echo stops at the ";" that ends the statement
            buf_txt.append(parts[0])
            for k, part in enumerate(parts[1:], 1):
                stmt = " ".join(t.strip() for t in buf_txt).strip()
                lead = 0
                while lead < len(buf_raw) - 1 and not buf_raw[lead].strip():
                    lead += 1  # the echo of a ";" statement starts at its first non-blank line
                lines.append(Line(buf_raw[lead:], "" if stmt.startswith("*") else stmt, start + lead))
                last = k == len(parts) - 1
                buf_raw = [tail] if last and tail.strip() else []
                buf_txt, start = [part], no
            if buf_txt == [""] or buf_txt == [] or all(not t.strip() for t in buf_txt):
                if not buf_raw:
                    buf_txt, start = [], None
            continue
        buf_txt.append(txt)
        if cont or state["block"]:
            continue
        joined = " ".join(t.strip() if k else t.rstrip() for k, t in enumerate(buf_txt)).strip()
        # A line that is only "///..." joins the next; if the joined line starts with "*" it is a
        # comment, as the authors' log shows (a "///" line with trailing text, then a "*" line, and no error;
        # doi:10.7910/DVN/HNPXO1 06_table6_alternative_outcomes.do).
        lines.append(Line(buf_raw, "" if joined.startswith("*") else joined, start))
        buf_raw, buf_txt, start = [], [], None
    if buf_raw:
        lines.append(Line(buf_raw, " ".join(t.strip() for t in buf_txt).strip(), start))
    return lines
