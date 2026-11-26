"""Parse text logs into command blocks and match them under docs/matching-rules.md.

Rules version is MATCH_RULES_VERSION; change it only with a dated entry in
docs/matching-rules.md.
"""
import difflib
import hashlib
import os
import re

MATCH_RULES_VERSION = "2026-11-24.14.7"

# Rules section 8. The wording table is data shared with the independent held-out scorer; both read the same file.
# A release ships a snapshot at harness/wording-table.tsv; OSE_WORDING_TABLE points elsewhere.
WORDING_TABLE = os.environ.get("OSE_WORDING_TABLE") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                    "wording-table.tsv")
if not os.path.exists(WORDING_TABLE):
    raise FileNotFoundError(f"wording table not found at {WORDING_TABLE}: set OSE_WORDING_TABLE (matching rules section 8)")
TEMPFILE = re.compile(r"(?:[A-Za-z]:)?[/\\]\S*?(?:St\d+\.\d+|ST_\w+\.tmp|ose\w+\.tmp|__\w+\.tmp)\b")


def _load_wording(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    for ln in raw.splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        rows.append((parts[0], re.compile(parts[1]), parts[2]))
    return rows, hashlib.sha256(raw.encode()).hexdigest()


WORDING, WORDING_HASH = _load_wording(WORDING_TABLE)


def tempfile_placeholder(line):
    """8.1: a tempfile path becomes <TEMPFILE> on both sides, in headline and strict."""
    return TEMPFILE.sub("<TEMPFILE>", line)


def reword(line):
    """8.2: the wording table, headline comparison only."""
    for _id, rx, rep in WORDING:
        line = rx.sub(rep, line)
    return line

HEADER_KEYS = ("name:", "log:", "log type:", "opened on:", "closed on:")
NUM = re.compile(r"^[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?(?:e[-+]\d+)?$")


class Block:
    """One echoed command and its output.

    `segs` are the log lines of the echo: the ". " line and its "> " lines, prefixes included. `key` is the raw echo
    with the "> " lines appended (alignment and evidence). Section 1 (.13): the scorer does not work out where the
    do-file's physical lines ended or which delimiter mode was in force. It reads an echo only when every reading
    gives the same answer (echo_kind): "blank", "directive" and "comment" are not counted; "plain" is counted and
    may earn credit, with `code` its command; anything else is "unread".

    An unread block is counted, never excluded, never joined (8.1) and never credited (section 3, AMBIGUOUS).
    """
    __slots__ = ("cmd", "key", "code", "kind", "out", "plain", "lineno", "segs", "sess")

    def __init__(self, segs, out, lineno):
        segs = segs if isinstance(segs, list) else [". " + segs]
        self.segs = segs
        self.cmd = "".join(s[2:] for s in segs)
        self.key = normkey(self.cmd)
        self.out = out
        self.plain = out
        self.lineno = lineno
        self.sess = 0  # recorded session of the log (rule 7a); parse_log sets it
        self.kind, self.code = echo_kind([s[2:] for s in segs])

    @property
    def ambiguous(self):
        return self.kind == "unread"

    @property
    def is_comment(self):
        return self.kind in ("blank", "directive", "comment")

    @property
    def is_logcmd(self):
        return bool(LOGCMD.match(_cmd_body(self.code)))

    @property
    def not_counted(self):
        return bool(NOT_COUNTED.match(self.code))

    @property
    def volatile(self):
        return volatile(self.code) if self.code else None

    @property
    def save_code(self):
        """The command text for the 8.1 save gate; empty (no join) unless the echo is plain."""
        return self.code


# A log line with any capture/quietly/noisily prefixes is a logging line, not counted (.11); read on _cmd_body.
LOGCMD = re.compile(r"^log\s+(using|close|off|on)\b")
DIRECTIVE = re.compile(r"^#\s*d(?:e(?:l(?:i(?:m(?:i(?:t)?)?)?)?)?)?\s+(?:;|cr)$")
MAX_ECHO_LINES = 8


def _rule_kind(code):
    """Everything section 1 and 8.1 read from a command's text."""
    return (code == "", bool(LOGCMD.match(_cmd_body(code))), bool(NOT_COUNTED.match(code)), volatile(code),
            is_save_cmd(code))


def _one_line_code(t):
    """Rules 4b and 4c: the command before a single trailing comment on a one-line echo with no quotes and no ";",
    else None."""
    if any(q in t for q in "\"`;") or t.startswith(("*", "#")):
        return None
    if t.count("/*") == 1 and t.count("*/") == 1 and t.endswith("*/") and "//" not in t:
        code = t[:t.index("/*")].strip()
    elif "/*" not in t and "*/" not in t and t.count("//") == 1 and t[t.index("//") - 1:t.index("//")] in (" ", "\t"):
        code = t[:t.index("//")].strip()
    else:
        return None
    return code or None


def echo_kind(texts):
    """Section 1 (.13). `texts` are the echo's log lines without their ". " and "> " prefixes. Returns (kind, code):
    kind is "blank", "directive", "comment", "plain" or "unread"; code is the command for "plain", else "".

    A "> " line is either a wrap of one do-file line or the next do-file line, and the log may be in CR or
    #delimit ; mode (a log can open after a #delimit). The rules below hold under every one of those readings."""
    n, t = len(texts), "".join(texts).strip()
    if not t:
        return "blank", ""
    if n == 1 and DIRECTIVE.match(normkey(t)):
        return "directive", ""
    block, semi_inside = "/*" in t or "*/" in t, ";" in t[:-1]
    if t.startswith("*") and not t.startswith("*/") and not block and "///" not in t and not semi_inside:
        return "comment", ""
    if n == 1 and t.startswith("//") and not block and not semi_inside:
        return "comment", ""
    if t.startswith("/*") and t.endswith("*/") and t.count("/*") == 1 and t.count("*/") == 1 and "//" not in t \
            and ";" not in t and len(t) >= 4:
        return "comment", ""
    if n == 1:
        code = _one_line_code(t)
        if code is not None:
            return "plain", normkey(code)
    if block or "//" in t or t.startswith(("*", "#")) or ";" in t or n > MAX_ECHO_LINES:
        return "unread", ""
    # Rule 4a (.14): no comment marker and no ";". A ";" anywhere is unread: a closing ";" is part of the command in
    # CR mode and a terminator in ";" mode. With no ";", the echo was not in ";" mode (an unclosed statement runs into
    # the next do-file line, echoed with "> " in this echo), except at the end of a do-file, which parse_log rules
    # out (rule 7). So each "> " is a wrap and the command is the join with nothing added. The check below can
    # only take credit away: it guards against a log whose wrap lines lost their trailing blanks.
    kinds = set()
    for mask in range(1 << (n - 1)):
        joined = texts[0] + "".join((" " if mask >> k & 1 else "") + texts[k + 1] for k in range(n - 1))
        kinds.add(_rule_kind(normkey(joined)))
        if len(kinds) > 1:
            return "unread", ""
    code = normkey(t)
    return ("plain", code) if code else ("unread", "")


def normkey(cmd):
    return re.sub(r"\s+", " ", cmd).strip()


def unwrap(lines):
    """Join "> " lines to the line before. Returns (texts, segs): texts as rules section 2 reads the log (each line
    with its "> " lines appended), and for an echoed command (". " line) the list of its log lines, else None.
    Output text is never altered beyond the join."""
    texts, segs = [], []
    for ln in lines:
        if ln.startswith("> ") and texts:
            texts[-1] = texts[-1] + ln[2:]
            if segs[-1] is not None:
                segs[-1].append(ln)
        else:
            texts.append(ln)
            segs.append([ln] if (ln == "." or ln.startswith(". ")) else None)
    return texts, segs


def _header_keep(lines):
    """Indices of lines outside log open/close header blocks and their dashed rules."""
    keep = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if re.match(r"^-{60,}$", s) and i + 1 < n and lines[i + 1].strip().startswith("name:"):
            i += 1
            continue
        if s.startswith("name:") and i + 1 < n and lines[i + 1].strip().startswith("log:"):
            j = i
            while j < n and any(lines[j].strip().startswith(k) for k in HEADER_KEYS):
                j += 1
            if j < n and re.match(r"^-{60,}$", lines[j].strip()):
                j += 1
            i = j
            continue
        keep.append(i)
        i += 1
    return keep


def strip_headers(lines):
    """Drop log open/close header blocks and their dashed rules."""
    return [lines[i] for i in _header_keep(lines)]


def parse_log(text):
    """Blocks of a log (section 1); each echo is read on its own (Block, echo_kind)."""
    return _parse(text)[0]


def _parse(text, record=False):
    """parse_log, and with record=True the CLI's stop record (section 3, .14.6). The record is found by its position:
    the transcript's last non-blank physical line, when it has the stop-line shape. It is taken out of the output, so
    it is never compared, and its owner is returned: the index of the block whose output it ends, or None when it
    falls where section 1 assigns output to no block (after a new log header, before the next echo). An "end of
    do-file" line directly before it, in the same block, is the engine's footer and is taken out too. A line with the
    same text anywhere else is ordinary output. Returns (blocks, record_text or None, owner)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    phys = [ln for ln in lines if ln.strip()]
    texts, segs = unwrap(lines)
    keep = _header_keep(texts)
    # Rule 7a (.14.1): a header or footer block removed between two kept lines is a session boundary. The log can hold
    # more than one recorded session (a log closed and opened again, with append); the next session's first echo says
    # nothing about whether the previous one's last statement had a next do-file line.
    cut = {pos for pos in range(1, len(keep)) if keep[pos] > keep[pos - 1] + 1}
    texts, segs = [texts[i] for i in keep], [segs[i] for i in keep]
    # Rule 7b (.14.3): output after a boundary and before the new session's first echo belongs to no block, as output
    # before a log's first echo does; it never joins the previous session's last block.
    rec = None
    if record and phys and STOP_RE.match(phys[-1]):
        rec = max(p for p, t in enumerate(texts) if t.strip())
        assert texts[rec] == phys[-1] and segs[rec] is None, "the stop record is the last physical line"
    owner, footer = None, None
    blocks, ends, sess, held = [], set(), 0, False
    for no, (ln, sg) in enumerate(zip(texts, segs), 1):
        if no - 1 in cut:
            sess += 1
            held = True
            if blocks:
                ends.add(len(blocks) - 1)
        if no - 1 == rec:
            owner = len(blocks) - 1 if blocks and not held else None
            continue
        if sg is not None:
            blocks.append(Block(sg, [], no))
            blocks[-1].sess = sess
            held = False
        elif blocks and not held:
            if rec is not None and no == rec and ln.strip() == "end of do-file" and rec not in cut:
                footer = (len(blocks) - 1, len(blocks[-1].out))
            blocks[-1].out.append(ln)
    # Rule 7 (.14): an echo read as plain is unread when it can be the last statement of a do-file: an "end of
    # do-file" line in its output, no echo after it, a session boundary before the next echo (7a, .14.1), or a
    # #delimit directive next. With no ";" it was in CR mode only
    # because a ";"-mode statement would have run into the next do-file line; here there may be no next line, and
    # the log cannot show whether the unclosed text ran. A log line or a session setting stays not counted: it is
    # not counted whether or not it ran.
    # A blank echo (an empty prompt) is not a statement and does not count as an echo after it; logs print
    # "end of do-file" after the empty prompt that follows a do-file's last statement, so its output is read too.
    for k, b in enumerate(blocks):
        if b.kind != "plain" or b.is_logcmd or b.not_counted:
            continue
        j = k + 1
        while j < len(blocks) and blocks[j].kind == "blank":
            j += 1
        tail = [ln for c in blocks[k:j] for ln in c.out]
        boundary = any(m in ends for m in range(k, j))
        if j == len(blocks) or boundary or blocks[j].kind == "directive" \
                or any(ln.strip() == "end of do-file" for ln in tail):
            b.kind, b.code = "unread", ""
    # The engine's footer before its stop record goes with the record. Rule 7 above has read it, as before .14.6.
    if footer is not None and footer[0] == owner:
        del blocks[owner].out[footer[1]]
    for b in blocks:
        b.plain = clean_out(b.out)
        b.out = clean_out(b.out, b.save_code)
    return blocks, (texts[rec] if rec is not None else None), owner


SAVE_NOTE = re.compile(r"^(?:\(file (?P<a>\S+) not found\)|file (?P<b>\S+) saved(?: as \.dta format)?)$")


def _is_save_note(text):
    m = SAVE_NOTE.match(text)
    return bool(m) and bool(TEMPFILE.fullmatch(m.group("a") or m.group("b")))


def join_tempfile_notes(lines):
    """8.1 (.6, narrowed in .7 and .8): only the two witnessed save notes on a tempfile path are joined across their
    wrap: "(file <tempfile> not found)" and "file <tempfile> saved[ as .dta format]". A line that starts one of
    these notes is joined with the following lines indented exactly four spaces only when the joined text is
    exactly one complete note (at most two continuation lines; the longer complete note wins). Any other line is
    never joined. Where the note wraps depends on the machine's path length. Callers apply this to the output
    of a save command only (clean_out); other commands' output keeps every line as printed."""
    out = []
    i, n = 0, len(lines)
    while i < n:
        k = _note_wrap(lines, i)
        if k:
            out.append(" ".join([lines[i].rstrip()] + [lines[i + j].strip() for j in range(1, k + 1)]))
            i += k + 1
        else:
            out.append(lines[i])
            i += 1
    return out


def _note_wrap(lines, i):
    """Number of continuation lines (2 or 1) that complete a wrapped save note starting at lines[i], else 0.
    Both lengths are tried and the longer complete note wins, so "file <t>" / "    saved" / "    as .dta format"
    joins all three lines instead of stopping at the shorter complete note."""
    first = lines[i].rstrip()
    if not re.match(r"^\(?file \S", first) or not TEMPFILE.search(first):
        return 0
    cont = []
    for k in (1, 2):
        if i + k >= len(lines) or not re.match(r"^    \S", lines[i + k]):
            break
        cont.append(lines[i + k].strip())
    for k in range(len(cont), 0, -1):
        if _is_save_note(" ".join([first] + cont[:k])):
            return k
    return 0


SAVE_CMD = re.compile(r"^sa(?:v|ve)?(?=\s|,|$)")


def is_save_cmd(code):
    """True for a save command (abbreviations sa, sav, save), after capture/quietly/noisily prefixes.
    `code` is the command with comments removed (command_code)."""
    return bool(SAVE_CMD.match(_cmd_body(code)))


def clean_out(lines, code=""):
    out = [ln.rstrip() for ln in lines]
    if is_save_cmd(code):
        out = join_tempfile_notes(out)
    # drop trailing "end of do-file" console lines and surrounding blanks
    while out and out[-1] == "":
        out.pop()
    while out and out[0] == "":
        out.pop(0)
    return out


def _decimals(tok):
    t = tok.replace(",", "").lower()
    if "e" in t:
        mant, ex = t.split("e")
        d = len(mant.split(".")[1]) if "." in mant else 0
        return d - int(ex)
    return len(t.split(".")[1]) if "." in t else 0


def _is_num(t):
    return bool(NUM.match(t.lower())) and any(c.isdigit() for c in t)


def token_cmp(a, b):
    """Compare expected token a with actual token b: 'exact', 'approx' or None (differs).

    Rules 2026-11-24.2: integers (no point, no exponent) must be equal in value; decimals must
    print the same number of decimals and lie within one unit of the expected last digit
    ('approx' when not identical); exponent forms are compared by value at the mantissa's precision.
    """
    if a == b:
        return "exact"
    if not (_is_num(a) and _is_num(b)):
        return None
    al, bl = a.lower(), b.lower()
    try:
        x = float(al.replace(",", ""))
        y = float(bl.replace(",", ""))
    except ValueError:
        return None
    if "." not in al and "e" not in al:  # integer
        return "exact" if ("." not in bl and "e" not in bl and x == y) else None
    if "e" not in al and _decimals(al) != _decimals(bl):
        return None
    if x == y:
        return "exact"
    unit = 10.0 ** (-_decimals(al))
    return "approx" if abs(x - y) <= unit * 1.000001 else None


def tokens_equal(a, b):
    return token_cmp(a, b) is not None


def line_cmp(a, b, strict=False):
    """Return (ok, n_approx). strict also requires identical spacing after right-trimming."""
    a, b = tempfile_placeholder(a), tempfile_placeholder(b)
    if not strict:
        a, b = reword(a), reword(b)
    if strict:
        pa, pb = re.split(r"(\s+)", a.rstrip()), re.split(r"(\s+)", b.rstrip())
        if len(pa) != len(pb) or any(pa[k] != pb[k] for k in range(1, len(pa), 2)):
            return False, 0
        ta, tb = pa[0::2], pb[0::2]
    else:
        ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False, 0
    n = 0
    for x, y in zip(ta, tb):
        c = token_cmp(x, y)
        if c is None:
            return False, 0
        n += c == "approx"
    return True, n


def lines_equal(a, b):
    return line_cmp(a, b)[0]


def block_diff(exp, act, plain=False):
    """Return None if outputs match, else a short description of the first difference."""
    e = list(exp.plain if plain else exp.out)
    a = list(act.plain if plain else act.out)
    if len(e) != len(a):
        # report first differing line
        for i in range(min(len(e), len(a))):
            if not lines_equal(e[i], a[i]):
                return f"line {i + 1}: expected {e[i]!r} got {a[i]!r}"
        return f"expected {len(e)} lines, got {len(a)}"
    for i, (x, y) in enumerate(zip(e, a)):
        if not lines_equal(x, y):
            return f"line {i + 1}: expected {x!r} got {y!r}"
    return None


def out_cmp(exp, act, strict=False, plain=False):
    """Compare two blocks' output. `plain` compares it without the 8.1 save-note join (an ambiguous row)."""
    eo, ao = (exp.plain, act.plain) if plain else (exp.out, act.out)
    if len(eo) != len(ao):
        return False, 0
    n = 0
    for x, y in zip(eo, ao):
        ok, k = line_cmp(x, y, strict)
        if not ok:
            return False, 0
        n += k
    return True, n


# Session settings that are not counted (versioned with the rules).
NOT_COUNTED = re.compile(r"^(?:(?:cap|capt|captu|captur|capture|qui|quie|quiet|quietl|quietly)\s+)?"
                         r"(?:set\s+(?:more|rmsg|linesize|pagesize|scrollbufsize|trace|logtype|tracedepth)\b|"
                         r"version\b|vers\b|pause\b)")
VOLATILE_CLOCK = re.compile(r"c\(\s*(?:current_date|current_time|hostname|username|pwd|memory|processors\w*)\s*\)|"
                            r"\$S_DATE|\$S_TIME|^timer\b|^pwd\b|^query\b|^creturn\b|^memory\b|^about\b")
VOLATILE_RNG = re.compile(r"\br(?:uniform|uniformint|normal|binomial|poisson|beta|chi2|exponential|gamma|"
                          r"hypergeometric|igaussian|logistic|nbinomial|t|weibull|weibullph)\s*\(|"
                          r"(?:^|:\s*)(?:bootstrap|bs|bsample|simulate|sample|splitsample|permute)\b")


def _cmd_body(key):
    """Command text without the capture/quietly/noisily prefixes."""
    return re.sub(r"^(?:(?:cap|capt|captu|captur|capture|qui|quie|quiet|quietl|quietly|n|no|noi|nois|noisi|"
                  r"noisil|noisily)\s+)+", "", key)


def volatile(key):
    body = _cmd_body(key)
    if VOLATILE_CLOCK.search(body):
        return "clock"
    if VOLATILE_RNG.search(body):
        return "rng"
    return None


def align_key(key):
    """Path-like tokens reduce to their basename for alignment only (authors' paths cannot appear in our run)."""
    def base(tok):
        q = tok.strip('"\'`')
        if "\\" in q or q.startswith("/") or q.startswith("~") or re.match(r"^[A-Za-z]:", q) or \
                (tok.startswith('"') and "/" in q):
            return re.split(r"[\\/]", q.rstrip("/\\"))[-1]
        return tok
    return " ".join(base(t) for t in key.split(" "))


STOP_RE = re.compile(r"^\*\* ose: (unsupported|error|crash):")
EXIT_CLASS = {1: "error", 2: "unsupported", 3: "crash"}  # the CLI's exit codes (io-contract)


def match_logs(expected_text, actual_text, exit_code=None, timed_out=False):
    """Match per rules 2026-11-24.2. Returns one row per counted or excluded expected block.

    Row fields: cmd, line, has_output, cls (MATCH, AMBIGUOUS, UNSUPPORTED, NOT_RUN, WRONG, ERROR, CRASH),
    excluded (None, 'clock', 'rng'), approx (count), strict (bool), ok (witnessed credit),
    ok_unwitnessed, why.
    """
    exp = parse_log(expected_text)
    # Rule 7c (.14.6): where the engine stopped. The process status decides whether it stopped; the transcript only
    # says where. The CLI writes its stop line (`** ose: <class>: ...`) as the transcript's last line exactly when it
    # exits 1 (error), 2 (unsupported) or 3 (crash), and never on exit 0.
    #  - exit 0: the run ended cleanly. A last line shaped like a stop line is ordinary output, compared as such.
    #  - exit 1, 2, 3: the run stopped, with that class. A stop-shaped last line is the CLI's record. parse finds it by
    #    position and takes it out (_parse): when it ends the last block's output that block is compared without it;
    #    when it falls in output that belongs to no block (after a new log header) the stop is held and the last
    #    block takes it. Text equal to the record elsewhere in the output is ordinary output.
    #  - timed_out, or any other status (a signal, a status outside the contract): the run stopped as a CRASH. The CLI
    #    wrote no record, so no line is taken out and the last block takes the stop. A timeout has no process status;
    #    the caller says so with timed_out=True, never with a stand-in code.
    #  - status unknown (None: scoring a transcript alone): a stop-shaped last line is read as a stop, and the run is
    #    never taken as a clean end, so the session-end fallback credits nothing. Both can only withhold credit.
    stop_kind, stop_held, stop_why = None, False, None
    known_clean = exit_code == 0 and not timed_out
    record = actual_text is not None and not timed_out and (exit_code is None or exit_code in EXIT_CLASS)
    act, rec, owner = _parse(actual_text, record=True) if record else \
        ((parse_log(actual_text) if actual_text is not None else []), None, None)
    if timed_out:
        stop_kind, stop_held, stop_why = "crash", True, "engine timed out"
    elif exit_code is not None and exit_code != 0 and exit_code not in EXIT_CLASS:
        stop_kind, stop_held, stop_why = "crash", True, f"engine exit status {exit_code}"
    elif rec is not None:
        stop_kind = EXIT_CLASS.get(exit_code, STOP_RE.match(rec).group(1))
        stop_why, stop_held = rec, owner is None
    elif exit_code in EXIT_CLASS:
        stop_kind, stop_held, stop_why = EXIT_CLASS[exit_code], True, f"engine exit code {exit_code}"
    sm = difflib.SequenceMatcher(a=[align_key(b.key) for b in exp], b=[align_key(b.key) for b in act],
                                 autojunk=False)
    pair = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pair[i1 + k] = j1 + k
    stop_j = len(act) - 1 if stop_kind else None
    cls_of_stop = {"unsupported": "UNSUPPORTED", "error": "ERROR", "crash": "CRASH"}
    rows, stopped = [], False
    last_aligned = max(pair.values(), default=-1)
    for i, b in enumerate(exp):
        if b.is_comment or b.is_logcmd or b.not_counted:
            continue
        j = pair.get(i)
        # Section 3 (.13): a row earns credit only when the expected and the actual echo are both plain.
        amb = b.kind != "plain" or (j is not None and act[j].kind != "plain")
        row = {"cmd": b.key, "line": b.lineno, "_sess": b.sess, "has_output": bool(b.plain if amb else b.out),
               "excluded": b.volatile, "approx": 0, "strict": False, "why": None, "echo_ambiguous": amb}
        if stopped:
            row.update(cls="NOT_RUN", why="after the engine stopped")
        elif j is None:
            if stop_kind and stop_j is not None and stop_j > last_aligned:
                # the engine stopped on a block we could not align; the first unaligned block takes the stop
                row.update(cls=cls_of_stop[stop_kind], why="engine stopped here (unaligned)")
                stopped = True
            else:
                row.update(cls="NOT_RUN", why="not run")
        else:
            ok, napx = out_cmp(b, act[j], plain=amb)
            if j == stop_j and stop_held:
                row.update(cls=cls_of_stop[stop_kind], why=stop_why)
                stopped = True
            elif j == stop_j and (not ok or stop_kind != "error"):
                # Only an ERROR can be the authors' own stop: their log can show the same Stata error at the same
                # command. A log made by Stata never shows the engine's UNSUPPORTED or CRASH, so output equal to the
                # authors' is never a match there (.14.6). The engine prints its own message on both, so this
                # changes no transcript it writes today; it makes the point a rule instead of a consequence.
                row.update(cls=cls_of_stop[stop_kind], why=(act[j].out[-2] if len(act[j].out) > 1 else stop_why))
                stopped = True
            elif ok and amb:
                row.update(cls="AMBIGUOUS", why="the echo does not settle what the command is")
                if j == stop_j:
                    stopped = True
            elif ok:
                row.update(cls="MATCH", approx=napx, strict=out_cmp(b, act[j], strict=True)[0])
                if j == stop_j:
                    stopped = True  # the authors' log shows the same stop
            else:
                row.update(cls="WRONG", why=block_diff(b, act[j], plain=amb))
        rows.append(row)
    # Witness rule (section 2, .14.2): a silent block is credited only if the next counted output-bearing block in
    # the same recorded session of the expected log matches. With none, the session-end fallback: credited if the
    # engine ended without a stop and that session has a matching output-bearing block. A header or footer block
    # (rule 7a) ends a session, so output from another session never witnesses a silent command.
    counted = [r for r in rows if not r["excluded"]]
    out_match_in = {r["_sess"] for r in counted if r["has_output"] and r["cls"] == "MATCH"}
    clean_end = stop_kind is None and known_clean
    for k, r in enumerate(counted):
        r["ok_unwitnessed"] = r["cls"] == "MATCH"
        if r["cls"] != "MATCH" or r["has_output"]:
            r["ok"] = r["cls"] == "MATCH"
            continue
        nxt = next((q for q in counted[k + 1:] if q["has_output"] or q["_sess"] != r["_sess"]), None)
        if nxt is not None and nxt["_sess"] == r["_sess"]:
            r["ok"] = nxt["cls"] == "MATCH"
        else:
            r["ok"] = clean_end and r["_sess"] in out_match_in
    for r in rows:
        del r["_sess"]
        if r["excluded"]:
            r["ok"] = r["ok_unwitnessed"] = None
    return rows


CLASSES = ("MATCH", "AMBIGUOUS", "UNSUPPORTED", "NOT_RUN", "WRONG", "ERROR", "CRASH")


def summarize(rows):
    c = [r for r in rows if not r["excluded"]]
    wo = [r for r in c if r["has_output"]]
    out = {
        "commands": len(c),
        "matched": sum(bool(r["ok"]) for r in c),
        "matched_unwitnessed": sum(bool(r["ok_unwitnessed"]) for r in c),
        "matched_strict": sum(bool(r["ok"]) and (r["strict"] or not r["has_output"]) for r in c),
        "with_output": len(wo),
        "with_output_matched": sum(bool(r["ok"]) for r in wo),
        "approx_tokens": sum(r["approx"] for r in c),
        "excluded_clock": sum(r["excluded"] == "clock" for r in rows),
        "excluded_rng": sum(r["excluded"] == "rng" for r in rows),
    }
    for k in CLASSES:
        out["cls_" + k] = sum(r["cls"] == k for r in c)
    return out
