"""Rules section 1 (.13), through the engine's own echo: each do-file here is run by the engine and its transcript
is scored with parse_log and match_logs.

.13 reads an echo only when every reading of it gives the same command: a "> " may be a wrap or a new do-file line,
and the log may be in CR or #delimit ; mode. Anything else is counted and never credited (AMBIGUOUS, or WRONG when
the output differs). The cases below are the reviewed cases from rules .9 to .11, with their .13 results.
"""
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ENGINE = os.path.join(HERE, "..", "..", "engine")
sys.path.insert(0, os.path.join(HERE, "..", "..", "harness"))
import logmatch as L  # noqa: E402

T = "/tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001"


def _run(tmp_path, src, files=None, end=True):
    """Run `src` through the engine and return its transcript. With end=True a `capture log close` line (not
    counted) is added, as the scored do-files end: under .14 rule 7 a statement with no echo after it may be the last
    of a do-file, which is not read."""
    do = tmp_path / "t.do"
    do.write_text(src + ("capture log close\n" if end else ""))
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text)
    tr = tmp_path / "t.log"
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(do), "--cwd", str(tmp_path),
                        "--transcript", str(tr)], env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return tr.read_text()


def _author_notes(text):
    """The engine prints each save note on one line; an author's log with a long tempfile path wraps it."""
    out = []
    for ln in text.split("\n"):
        if re.match(r"^\(file \S+ not found\)$", ln):
            out += [f"(file {T}", "    not found)"]
        elif re.match(r"^file \S+ saved as \.dta format$", ln):
            out += [f"file {T}", "    saved", "    as .dta format"]
        else:
            out.append(ln)
    return "\n".join(out)


def _rows(rows):
    return [(r["cmd"], r["cls"], bool(r["ok"])) for r in rows]


DO = "\n".join([
    "set obs 2",
    "gen x = 1",
    "tempfile t",
    "save `t', replace",                                  # plain: read, joined (8.1)
    "/// a description of the next step",                # a continued command: counted, not read
    "save `t', replace",
    "s/* join */ave `t', replace",                       # a same-line comment inside the command: not read
    "/* before */ * only a note",                         # not read
    "* a plain note",                                     # a comment
    "// a long note about the plot that runs well past the line width and so it is wrapped by the log",
    "display \"A\" ///",
    "  \"B\"",
    "#delimit ;",
    "save `t', replace;",                                 # plain under ";": read, joined
    "// note",                                            # a line comment, then a statement on the next line
    "save `t', replace;",
    "/* note */;",                                        # an empty statement: not read
    "sum x;",
    "#delimit cr",
    "display 1",
    "",
])


def test_engine_echo_kinds(tmp_path):
    actual = _run(tmp_path, DO)
    kinds = [(b.kind, b.code) for b in L.parse_log(actual) if b.kind != "blank"]
    assert kinds == [
        ("plain", "set obs 2"), ("plain", "gen x = 1"), ("plain", "tempfile t"), ("plain", "save `t', replace"),
        ("unread", ""), ("unread", ""), ("unread", ""), ("comment", ""),
        ("unread", ""),                       # the long // comment, wrapped: under ";" it could run on
        ("unread", ""),                       # display "A" /// "B"
        # .14: under ";" each statement carries a ";", and the echo cannot say whether it is part of the command
        ("directive", ""), ("unread", ""), ("unread", ""), ("unread", ""), ("unread", ""),
        ("directive", ""), ("plain", "display 1"), ("plain", "capture log close")]


def test_plain_saves_join_and_unread_saves_do_not(tmp_path):
    actual = _run(tmp_path, DO)
    rows = L.match_logs(_author_notes(actual), actual, exit_code=0)
    saves = [r for r in rows if re.search(r"(^|> |\s)save `t'|ave `t'", r["cmd"])]
    plain = [r for r in saves if not r["echo_ambiguous"]]
    unread = [r for r in saves if r["echo_ambiguous"]]
    assert len(plain) == 1 and all(r["cls"] == "MATCH" and r["strict"] and r["ok"] for r in plain)
    assert len(unread) == 4 and all(r["cls"] == "WRONG" and not r["ok"] for r in unread)
    # Each unread row is counted; none earns credit of any kind.
    assert all(not (r["ok"] or r["ok_unwitnessed"] or r["strict"]) for r in rows if r["echo_ambiguous"])


def test_rules11_a_comment_never_credited_as_a_silent_command(tmp_path):
    # The author's log runs `local` on the line after a `//` comment under ";"; the engine's log shows one comment
    # line with the same text. Before .13 the pair scored a strict MATCH.
    reference = _run(tmp_path, "#delimit ;\n// a\nlocal value 4271;\n#delimit cr\ndisplay 8\n")
    comment_only = _run(tmp_path, "// alocal value 4271;\n#delimit cr\ndisplay 8\n")
    exp = [b for b in L.parse_log(reference) if b.key.startswith("// a")]
    act = [b for b in L.parse_log(comment_only) if b.key.startswith("// a")]
    assert exp[0].key == act[0].key and exp[0].kind == "unread" and act[0].kind == "comment"
    rows = L.match_logs(reference, comment_only, exit_code=0)
    assert _rows(rows) == [("// alocal value 4271;", "AMBIGUOUS", False), ("display 8", "MATCH", True)]
    assert not (rows[0]["strict"] or rows[0]["ok_unwitnessed"])
    # And the same log against itself: still no credit for the unread row.
    assert _rows(L.match_logs(reference, reference, exit_code=0))[0] == ("// alocal value 4271;", "AMBIGUOUS",
                                                                         False)


@pytest.mark.parametrize("tail", ["/// final comment", "// final comment"])
def test_rules11_b_child_ending_in_a_comment(tmp_path, tail):
    actual = _run(tmp_path, "do child\ndisplay 8\n", {"child.do": tail})
    rows = L.match_logs(actual, actual, exit_code=0)
    assert _rows(rows) == [("do child", "MATCH", True), ("display 8", "MATCH", True)]


def test_rules11_c_directive_text_after_a_statement(tmp_path):
    actual = _run(tmp_path, "#delimit ;\ndisplay 1; #delimit cr;\n// note\ndisplay 2;\n#delimit cr\ndisplay 3\n")
    assert all(f"\n{n}\n" in actual for n in (1, 2, 3))
    rows = L.match_logs(actual, actual, exit_code=0)
    # The engine echoes the first statement of the line; `// note` then `> display 2;` is not read.
    assert [(c, k) for c, k, _ in _rows(rows)] == [
        ("display 1;", "AMBIGUOUS"), ("// notedisplay 2;", "AMBIGUOUS"), ("display 3", "MATCH")]
    assert not rows[1]["ok"]
    # A log that echoes the whole physical line: two statements in one echo are not read.
    whole = actual.replace(". display 1;\n", ". display 1; #delimit cr;\n")
    assert whole != actual
    rows = L.match_logs(whole, whole, exit_code=0)
    assert [(c, k) for c, k, _ in _rows(rows)][0] == ("display 1; #delimit cr;", "AMBIGUOUS")


def test_rules10_a_narrow_wrap_then_a_wider_one(tmp_path):
    src = "\n".join(["set linesize 40", "#delimit ;", "// " + "x" * 34 + "* still a line comment",
                     "display 7;", "#delimit cr", "set linesize 80", "// " + "y" * 96, "display 8", ""])
    actual = _run(tmp_path, src)
    assert "\n7\n" in actual and "\n8\n" in actual
    rows = L.match_logs(actual, actual, exit_code=0)
    first = [r for r in rows if "display 7" in r["cmd"]]
    assert len(first) == 1 and first[0]["cls"] == "AMBIGUOUS" and not first[0]["ok"]  # counted, never left out
    assert rows[-1]["cmd"] == "display 8" and rows[-1]["cls"] == "MATCH" and rows[-1]["ok"]


def test_rules10_b_empty_statement_earns_no_credit(tmp_path):
    src = "\n".join(["set linesize 40", "// " + "y" * 55, "#delimit ;", "// " + "x" * 34 + "display 9", ";",
                     "#delimit cr", "display 8", "display 7", ""])
    actual = _run(tmp_path, src)
    assert "\n9\n" not in actual and "\n8\n" in actual
    rows = L.match_logs(actual.replace("\n7\n", "\n6\n"), actual, exit_code=0)
    by = {r["cmd"]: r for r in rows}
    assert by["display 8"]["cls"] == "MATCH" and by["display 8"]["ok"]
    assert by["display 7"]["cls"] == "WRONG"
    s = L.summarize(rows)
    assert s["matched"] == 1 and s["matched_unwitnessed"] == 1 and s["matched_strict"] == 1
    assert all(not r["ok"] for r in rows if r["echo_ambiguous"])


def test_rules10_c_commented_directive(tmp_path):
    note = "// " + "z" * 76 + "display 5"
    actual = _run(tmp_path, "\n".join(["/* preface */ #delimit ;", note, "#delimit cr", note, "display 4", ""]))
    assert "\n5\n" not in actual and "\n4\n" in actual
    rows = L.match_logs(actual, actual, exit_code=0)
    assert rows[-1]["cmd"] == "display 4" and rows[-1]["cls"] == "MATCH" and rows[-1]["ok"]
    assert all(r["cls"] == "AMBIGUOUS" and not r["ok"] for r in rows[:-1]) and len(rows) == 4


def test_rules9_continued_save_is_counted(tmp_path):
    actual = _run(tmp_path, "tempfile t\nset obs 1\n/// keep this\nsave `t', replace\ndisplay 2\n")
    rows = L.match_logs(actual, actual, exit_code=0)
    cont = [r for r in rows if r["cmd"].endswith("save `t', replace")]
    assert len(cont) == 1 and cont[0]["cls"] == "AMBIGUOUS" and not cont[0]["ok"]


def test_empty_continuation_line_is_echoed_with_its_prefix(tmp_path):
    # A `///` before a blank line: logs print the continuation as "> " (with its blank), as for an empty ". ".
    actual = _run(tmp_path, "///a note\n\ndisplay 2\n")
    assert "\n> \n" in actual
    blocks = L.parse_log(actual)
    assert [b.segs for b in blocks if b.key.startswith("///")] == [[". ///a note", "> "]]


@pytest.mark.parametrize("strict", [False, True])
def test_unit_separator_in_output_is_compared(strict):
    exp = L.parse_log(". display x\nA\x1fB\n")
    act = L.parse_log(". display x\nAB\n")
    assert exp[0].out == ["A\x1fB"]
    assert L.out_cmp(exp[0], act[0], strict=strict)[0] is False
    assert L.match_logs(". display x\nA\x1fB\n", ". display x\nAB\n", exit_code=0)[0]["cls"] == "WRONG"


def test_log_lines_are_not_counted_whatever_their_prefixes():
    log = "\n".join([". quietly log using a", ". cap noi log close", ". qui log off", ". noisily log on",
                     ". capture log using b", ". display 1", "1", ". logit y x", ""])
    rows = L.match_logs(log, log, exit_code=0)
    assert [r["cmd"] for r in rows] == ["display 1", "logit y x"]


# Rules .14. Each pair below is two do-files whose echoes are the same and whose commands differ; a separate readback
# run shows the difference. The echo cannot say which one ran, so neither earns credit. A nearby plain assignment
# and its display are the positive control.

def _readback(tmp_path, src, name):
    out = _run(tmp_path, src + f'display "[`{name}\']"\n')
    return [ln for ln in out.split("\n") if ln.startswith("[")]


LONG = "local fixture " + "q" * 63          # 77 characters: with ". " it fills the echo width of 79 exactly
CONTROL = 'local near abc\ndisplay "`near\'"\nlocal wide ' + "w" * 80 + '\ndisplay length("`wide\'")\n'


def test_rules14_wrap_or_new_line_under_semicolon(tmp_path):
    one_line = "#delimit ;\n" + LONG + "rest;\n#delimit cr\n"
    two_lines = "#delimit ;\n" + LONG + "\nrest;\n#delimit cr\n"
    a, b = _run(tmp_path, one_line + CONTROL), _run(tmp_path, two_lines + CONTROL)
    ea = [blk.segs for blk in L.parse_log(a) if blk.key.startswith("local fixture")]
    eb = [blk.segs for blk in L.parse_log(b) if blk.key.startswith("local fixture")]
    assert ea == eb and len(ea[0]) == 2                       # the same two-line echo
    ra = _readback(tmp_path, "#delimit ;\n" + LONG + "rest;\n#delimit cr\n", "fixture")
    rb = _readback(tmp_path, "#delimit ;\n" + LONG + "\nrest;\n#delimit cr\n", "fixture")
    assert len(ra[0]) + 1 == len(rb[0])                       # different commands: a blank at the new line
    for exp, act in ((a, b), (b, a), (a, a)):
        rows = L.match_logs(exp, act, exit_code=0)
        fx = [r for r in rows if r["cmd"].startswith("local fixture")]
        assert len(fx) == 1 and fx[0]["cls"] == "AMBIGUOUS" and fx[0]["echo_ambiguous"]
        assert not (fx[0]["ok"] or fx[0]["ok_unwitnessed"] or fx[0]["strict"])
        # positive control: plain CR assignments, one wrapped by the log, witnessed by their displays
        ctl = [(r["cmd"][:16], r["cls"], bool(r["ok"]), r["strict"]) for r in rows if not r["echo_ambiguous"]]
        assert ctl == [("local near abc", "MATCH", True, True), ('display "`near\'"', "MATCH", True, True),
                       ("local wide " + "w" * 5, "MATCH", True, True), ('display length("', "MATCH", True, True)]
        assert [blk.kind for blk in L.parse_log(exp) if blk.key.startswith("local wide")] == ["plain"]


def test_rules14_trailing_semicolon_cr_or_semicolon_mode(tmp_path):
    cr = "local fixture abc;\nlocal other xyz;\n"
    semi = "#delimit ;\nlocal fixture abc;\nlocal other xyz;\n#delimit cr\n"
    assert _readback(tmp_path, cr, "fixture") == ["[abc;]"]
    assert _readback(tmp_path, semi, "fixture") == ["[abc]"]
    a = _run(tmp_path, cr + CONTROL)
    b = _run(tmp_path, semi + CONTROL).replace(". #delimit ;\n", "", 1)   # a log opened after the directive
    assert "#delimit ;" not in b
    for exp, act in ((a, b), (b, a)):
        rows = L.match_logs(exp, act, exit_code=0)
        fx = [r for r in rows if r["cmd"] == "local fixture abc;"]
        assert len(fx) == 1 and fx[0]["cls"] == "AMBIGUOUS" and not (fx[0]["ok"] or fx[0]["ok_unwitnessed"])
        assert [r["cls"] for r in rows if r["cmd"].startswith("display")] == ["MATCH", "MATCH"]


def test_rules14_last_statement_of_a_do_file_is_not_read(tmp_path):
    actual = _run(tmp_path, "do child\ndisplay 8\n", {"child.do": "local y 2\nlocal z 1\n"})
    kinds = {blk.key: blk.kind for blk in L.parse_log(actual)}
    assert kinds["local y 2"] == "plain" and kinds["local z 1"] == "unread"
    # and with no echo after it at all
    assert [blk.kind for blk in L.parse_log(_run(tmp_path, "display 8\n", end=False))] == ["unread", "blank"]
    rows = L.match_logs(actual, actual, exit_code=0)
    assert [(c, k, ok) for c, k, ok in _rows(rows)] == [
        ("do child", "MATCH", True), ("local y 2", "MATCH", True), ("local z 1", "AMBIGUOUS", False),
        ("display 8", "MATCH", True)]


# Rules .14.1: a log file can hold more than one recorded session. The next session's first echo is not evidence that
# the previous session's last statement had a next do-file line, so rule 7 stops at a session boundary.

def _session(tmp_path, name, body):
    """The engine's own log file for a do-file that opens `name` and runs `body`."""
    (tmp_path / (name + ".do")).write_text(f"log using {name}.log, text replace\n" + body)
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(tmp_path / (name + ".do")), "--cwd",
                        str(tmp_path), "--transcript", str(tmp_path / (name + ".tr"))],
                       env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    text = (tmp_path / (name + ".log")).read_text()
    assert "opened on:" in text
    return text


def test_rules14_1_session_boundary_ends_a_do_file(tmp_path):
    first = _session(tmp_path, "s1", "local y 2\nlocal z 1\n")               # the log ends with the run
    second = _session(tmp_path, "s2", "display 8\nlog close\n")
    two = first + second                                                        # one file, two sessions
    kinds = [(blk.key, blk.kind) for blk in L.parse_log(two)]
    assert ("local y 2", "plain") in kinds and ("local z 1", "unread") in kinds
    assert ("display 8", "plain") in kinds
    rows = {c: (k, ok) for c, k, ok in _rows(L.match_logs(two, two, exit_code=0))}
    assert rows["local z 1"] == ("AMBIGUOUS", False) and rows["display 8"] == ("MATCH", True)
    # control: the same statement with a logged next statement in its own session stays plain
    closed = _session(tmp_path, "s3", "local y 2\nlocal z 1\nlog close\n") + second
    assert ("local z 1", "plain") in [(blk.key, blk.kind) for blk in L.parse_log(closed)]
    # a header at the very start of a log is not a boundary between two echoes
    assert [blk.kind for blk in L.parse_log(second)][:1] == ["plain"]


def test_rules14_2_witness_stays_in_its_session(tmp_path):
    """Section 2, .14.2: a silent command's witness is the next output-bearing block in the same recorded session;
    with none, the session-end fallback looks only at that session."""
    second = _session(tmp_path, "s2", "display 8\nlog close\n")
    # Under .14.1 the second session's display witnessed the first session's silent `local y 2`.
    two = _session(tmp_path, "s1", "local y 2\nlocal z 1\n") + second
    rows = {c: (k, ok) for c, k, ok in _rows(L.match_logs(two, two, exit_code=0))}
    assert rows["local y 2"] == ("MATCH", False)               # matched, unwitnessed only
    assert rows["local z 1"] == ("AMBIGUOUS", False) and rows["display 8"] == ("MATCH", True)
    unw = {r["cmd"]: r["ok_unwitnessed"] for r in L.match_logs(two, two, exit_code=0)}
    assert unw["local y 2"] is True
    # Control: a witness in its own session still credits it.
    own = _session(tmp_path, "s3", "local y 2\ndisplay 5\nlocal z 1\n") + second
    rows = {c: (k, ok) for c, k, ok in _rows(L.match_logs(own, own, exit_code=0))}
    assert rows["local y 2"] == ("MATCH", True) and rows["display 5"] == ("MATCH", True)
    # Session-end fallback: no later output in its session, but that session has a matching output: credited.
    tail = _session(tmp_path, "s4", "display 5\nlocal y 2\nlocal z 1\n") + second
    rows = {c: (k, ok) for c, k, ok in _rows(L.match_logs(tail, tail, exit_code=0))}
    assert rows["local y 2"] == ("MATCH", True)
    # ... and the fallback does not borrow from another session: a wrong display in session 1 is not rescued by
    # session 2's match.
    bad = tail.replace(". display 5\n5\n", ". display 5\n6\n", 1)
    assert bad != tail
    rows = {c: (k, ok) for c, k, ok in _rows(L.match_logs(tail, bad, exit_code=0))}
    assert rows["display 5"] == ("WRONG", False) and rows["local y 2"] == ("MATCH", False)


def test_rules14_3_output_before_a_session_s_first_echo_joins_no_block(tmp_path):
    """Section 1, .14.3: a log opened inside a loop prints output before its first top-level echo. Those lines belong
    to no block; they never join the previous session's last block, so they cannot change the first session's rows."""
    native = _session(tmp_path, "s1", "display 5\nlocal y 2\nlocal z 1\n")
    assert native.endswith("\n. local z 1\n. \n")
    loop = "forvalues i = 1/1 {\n  log using s2.log, text replace\n  display 9\n}\ndisplay 8\nlog close\n"
    (tmp_path / "s2.do").write_text(loop)
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(tmp_path / "s2.do"), "--cwd", str(tmp_path),
                        "--transcript", str(tmp_path / "s2.tr")],
                       env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    second = (tmp_path / "s2.log").read_text()
    assert re.search(r"opened on:.*\n9\n\. display 8\n", second)        # the engine's log: output before the echo

    def s1(exp, act):
        keep = ("display 5", "local y 2", "local z 1")
        return [r for r in _rows(L.match_logs(exp, act, exit_code=0)) if r[0] in keep]
    # The engine's log ends with an empty prompt; a log cut short (a run stopped before its next prompt) ends on the
    # counted echo `local z 1`. In both, the second session's leading output joins no block.
    for first in (native, native[:-len(". \n")]):
        two = first + second
        assert [b.out for b in L.parse_log(two) if b.key == "local z 1"][0] == []
        other = first + second.replace("\n9\n. display 8", "\n7\n. display 8", 1)
        assert other != two
        base = s1(two, two)
        assert base == [("display 5", "MATCH", True), ("local y 2", "MATCH", True),
                        ("local z 1", "AMBIGUOUS", False)]
        # varying only the next session's leading output, on either side, changes no row of the first session
        assert s1(two, other) == base and s1(other, two) == base and s1(other, other) == base


def test_rules14_1_scorer_reads_the_displayed_echo_only(tmp_path):
    """Section 1, .14.1, stated limit: the echo shows a tab as blanks and section 2 merges runs of blanks, so two
    commands that differ only there read as the same command. A readback shows they differ; the scorer cannot."""
    tab, blank = 'local s "a\tb"\n', 'local s "a b"\n'
    assert _readback(tmp_path, tab, "s") != _readback(tmp_path, blank, "s")
    a, b = _run(tmp_path, tab + "display 8\n"), _run(tmp_path, blank + "display 8\n")
    assert [blk.key for blk in L.parse_log(a)][0] == [blk.key for blk in L.parse_log(b)][0]
    rows = _rows(L.match_logs(a, b, exit_code=0))
    assert rows[:2] == [('local s "a b"', "MATCH", True), ("display 8", "MATCH", True)]


def test_rules14_4_a_stop_after_a_new_log_header_still_stops(tmp_path):
    """Section 3, .14.4: a command that opens a log and then fails before the next echo leaves the engine's stop line
    after the new header, in output that belongs to no block (.14.3). The run still stopped there: that command takes
    the stop, and the session-end fallback credits nothing. Control: the same run with the file present."""
    src = ("display 5\nlocal y 2\nforvalues i = 1/1 {\n  log using s2.log, text replace\n  display 9\n"
           "  use part.dta\n}\ndisplay 8\nlog close\n")

    def run(name, present):
        d = tmp_path / name
        d.mkdir()
        if present:
            pre = d / "mk.do"
            pre.write_text("set obs 1\ngen x = 1\nsave part.dta\n")
            q = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(pre), "--cwd", str(d)],
                               env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
            assert q.returncode == 0, q.stderr
        (d / "t.do").write_text(src)
        p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(d / "t.do"), "--cwd", str(d),
                            "--transcript", str(d / "t.tr")],
                           env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
        return p.returncode, (d / "t.tr").read_text()

    def rows(exp, act, code):
        return {c: (k, ok) for c, k, ok in _rows(L.match_logs(exp, act, exit_code=code))}

    code_ok, good = run("ok", True)
    code_bad, bad = run("bad", False)
    assert code_ok == 0 and code_bad == 1
    # the stop line falls after the new log header, before any echo: it belongs to no block
    assert re.search(r"opened on:.*\n9\n.*\*\* ose: error: ", bad, re.S) and ". display 8" not in bad
    assert not any(ln.startswith("** ose:") for b in L.parse_log(bad) for ln in b.out)
    # The loop echoes its numbered lines, so it is an unread, output-bearing row. The same run as one plain call
    # (a program `f` holding the loop body; the transcripts are edited, as `program` is not built here) prints
    # nothing before the header, so the silent rows before it rest on the session-end fallback.
    echo = re.compile(r"^\. forvalues i = 1/1 \{\n(?:  \d\. .*\n)+", re.M)
    assert echo.search(good) and echo.search(bad)
    call_good, call_bad = echo.sub(". f\n", good), echo.sub(". f\n", bad)
    for exp, act, failing in ((good, bad, "forvalues i = 1/1 {"), (call_good, call_bad, "f")):
        control = rows(exp, exp, 0)
        assert control["display 5"] == ("MATCH", True) and control["display 8"] == ("MATCH", True)
        cut = "\n".join(ln for ln in act.split("\n") if not ln.startswith("** ose:"))
        for a, code, cls in ((act, 1, "ERROR"), (act, None, "ERROR"), (cut, 1, "ERROR"), (cut, 2, "UNSUPPORTED")):
            r = rows(exp, a, code)
            assert r[failing] == (cls, False), (failing, code, r)
            assert r["display 8"] == ("NOT_RUN", False) and r["display 5"] == ("MATCH", True)
            if failing == "f":
                assert r["local y 2"] == ("MATCH", False)      # the run stopped: no session-end credit
    calls = rows(call_good, call_good, 0)
    # clean end: the fallback credits `local y 2`; `f` has a session boundary next, so rule 7a leaves it unread
    assert calls["local y 2"] == ("MATCH", True) and calls["f"] == ("AMBIGUOUS", False)


def _status_rows(exp, act, code):
    return {r["cmd"]: (r["cls"], bool(r["ok"]), r["why"]) for r in L.match_logs(exp, act, exit_code=code)}


def test_rules14_5_any_failing_process_status_stops_the_run(tmp_path):
    """Section 3, .14.5: the process status decides whether the run stopped. A process killed by a signal (the harness
    sees a negative status), a timeout, or any status outside the CLI's 0-3 contract writes no stop line, and it is a
    CRASH stop all the same: the last block takes it and the session-end fallback credits nothing. With no status at
    all, a clean end cannot be shown, so the fallback credits nothing either. Control: status 0 on the same
    transcript credits the silent command through the fallback."""
    full = _run(tmp_path, "display 5\nlocal y 2\nlocal z 1\n")
    # the partial transcript of a process killed after echoing `local z 1`: a prefix with no stop line
    cut = full[:full.index(". local z 1\n") + len(". local z 1\n")]
    assert not any(ln.startswith("** ose:") for ln in cut.split("\n"))
    r = _status_rows(full, cut, 0)
    assert r["display 5"][:2] == ("MATCH", True) and r["local y 2"][:2] == ("MATCH", True)   # fallback credit
    for code in (3, -15, -9, 137, 4):
        r = _status_rows(full, cut, code)
        assert r["local z 1"][:2] == ("CRASH", False), (code, r)
        assert r["local z 1"][2] == (f"engine exit code {code}" if code == 3 else f"engine exit status {code}")
        assert r["display 5"][:2] == ("MATCH", True)
        assert r["local y 2"][:2] == ("MATCH", False), (code, r)                 # the run stopped: no fallback
    for code in (1, 2):
        r = _status_rows(full, cut, code)
        assert r["local z 1"][:2] == ({1: "ERROR", 2: "UNSUPPORTED"}[code], False)
        assert r["local y 2"][:2] == ("MATCH", False)
    r = _status_rows(full, cut, None)                                           # transcript only
    assert r["local y 2"][:2] == ("MATCH", False) and r["display 5"][:2] == ("MATCH", True)
    assert {cls for cls, _, _ in r.values()} <= {"MATCH", "AMBIGUOUS"}


def test_rules14_5_exit_0_reads_a_stop_shaped_last_line_as_output(tmp_path):
    """Section 3, .14.5: the CLI writes its stop line only when it exits 1, 2 or 3. On exit 0 a last line that looks
    like one is ordinary output. Here a log opened inside a loop is followed by a displayed diagnostic-shaped string,
    which section 1 leaves in output that belongs to no block. Paired with the genuine stop: the same do-file with a
    failing `use` exits 1, and that command takes the stop."""
    def run(name, body):
        d = tmp_path / name
        d.mkdir()
        (d / "t.do").write_text("display 5\nlocal y 2\nforvalues i = 1/1 {\n  log using s2.log, text replace\n"
                                f"  {body}\n}}\n")
        p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(d / "t.do"), "--cwd", str(d),
                            "--transcript", str(d / "t.tr")],
                           env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
        return p.returncode, (d / "t.tr").read_text()

    code_ok, shaped = run("ok", 'display "** ose: error: not a stop"')
    code_bad, failed = run("bad", "use missing_part.dta")
    assert code_ok == 0 and code_bad == 1
    assert re.search(r"opened on:.*\n\*\* ose: error: not a stop\n", shaped)
    assert not any(ln.startswith("** ose:") for b in L.parse_log(shaped) for ln in b.out)
    # The native transcript ends with the empty prompt; a cut-short one ends on the shaped line itself.
    lines = shaped.rstrip("\n").split("\n")
    assert lines[-1] == ". "
    cut_shaped = "\n".join(lines[:-1]) + "\n"
    assert cut_shaped.rstrip("\n").split("\n")[-1] == "** ose: error: not a stop"
    # As one plain call (a program `f` holding the loop body; edited, as `program` is not built here), the silent
    # `local y 2` rests on the session-end fallback.
    echo = re.compile(r"^\. forvalues i = 1/1 \{\n(?:  \d\. .*\n)+", re.M)
    for exp in (shaped, cut_shaped):
        for e, failing in ((exp, "forvalues i = 1/1 {"), (echo.sub(". f\n", exp), "f")):
            r = _status_rows(e, e, 0)
            assert r[failing][:2] == ("AMBIGUOUS", False), r            # unread at the session boundary, not ERROR
            assert r["display 5"][:2] == ("MATCH", True)
            if failing == "f":
                assert r["local y 2"][:2] == ("MATCH", True)          # clean end: fallback credit
            assert not {cls for cls, _, _ in r.values()} & {"ERROR", "UNSUPPORTED", "CRASH"}
    # Transcript-only scoring cannot tell the two apart (the stated limit): with no status, the cut-short shaped line
    # reads as a stop, which can only withhold credit.
    e = echo.sub(". f\n", cut_shaped)
    r = _status_rows(e, e, None)
    assert r["f"][:2] == ("ERROR", False) and r["local y 2"][:2] == ("MATCH", False)
    # The genuine stop after the header, exit 1: the failing command takes it.
    assert re.search(r"opened on:.*\n.*\*\* ose: error: ", failed, re.S)
    for e, failing in ((failed, "forvalues i = 1/1 {"), (echo.sub(". f\n", failed), "f")):
        r = _status_rows(e, e, 1)
        assert r[failing][:2] == ("ERROR", False) and r[failing][2].startswith("** ose: error: ")
        if failing == "f":
            assert r["local y 2"][:2] == ("MATCH", False)


REC = "** ose: error: file missing_part.dta not found"


def test_rules14_6_the_stop_record_is_found_by_position(tmp_path):
    """Section 3, .14.6: the CLI's stop record is the transcript's last line, and the scorer finds it by that position,
    never by its text. Here a command prints a line equal to the record, opens a log and then genuinely fails after
    the new header. The record is the line after the header; the equal line before the header is ordinary output.
    The failing command takes the stop (ERROR) whatever the reference shows before the header. Before .14.6 the
    scorer took out the equal line instead and, against a reference without it, gave the failing command AMBIGUOUS
    and ran on as if it had ended cleanly."""
    def run(name, body, present):
        d = tmp_path / name
        d.mkdir()
        if present:
            pre = d / "mk.do"
            pre.write_text("set obs 1\ngen x = 1\nsave missing_part.dta\n")
            q = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(pre), "--cwd", str(d)],
                               env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
            assert q.returncode == 0, q.stderr
        (d / "t.do").write_text("display 5\nlocal y 2\nforvalues i = 1/1 {\n" + body
                                + "  log using s2.log, text replace\n  use missing_part.dta\n}\ndisplay 8\n")
        p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(d / "t.do"), "--cwd", str(d),
                            "--transcript", str(d / "t.tr")],
                           env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
        return p.returncode, (d / "t.tr").read_text()

    shown = f'  display "{REC}"\n'
    code_bad, bad = run("bad", shown, False)          # prints the record's text, then fails after the header
    code_ref, ref = run("ref", shown, True)           # the same do-file, file present: runs to the end
    code_ref0, ref0 = run("ref0", "", True)           # a reference that prints nothing before the header
    assert (code_bad, code_ref, code_ref0) == (1, 0, 0)
    tail = [ln for ln in bad.split("\n") if ln.strip()]
    assert tail[-1] == REC and tail.count(REC) == 2
    assert re.search(r"\n" + re.escape(REC) + r"\n-+\n.*opened on:.*\n" + re.escape(REC) + r"\n$", bad, re.S)
    # The loop echoes its body, which differs between `bad` and `ref0`; as one plain call `f` (edited, as `program`
    # is not built here) the rows align and the silent `local y 2` rests on the session-end fallback.
    echo = re.compile(r"^\. forvalues i = 1/1 \{\n(?:  \d\. .*\n)+", re.M)
    f_bad, f_ref, f_ref0 = (echo.sub(". f\n", t) for t in (bad, ref, ref0))
    blocks, rec, owner = L._parse(f_bad, record=True)
    assert rec == REC and owner is None                                   # held: the record joins no block
    assert [b.out for b in blocks if b.key == "f"] == [[REC]]            # the equal line stays as output
    for exp, act in ((ref, bad), (f_ref, f_bad), (f_ref0, f_bad)):
        failing = "f" if act is f_bad else "forvalues i = 1/1 {"
        r = _status_rows(exp, act, 1)
        assert r[failing][:2] == ("ERROR", False) and r[failing][2] == REC, (failing, r)
        assert r["display 8"][:2] == ("NOT_RUN", False) and r["display 5"][:2] == ("MATCH", True)
        if failing == "f":
            assert r["local y 2"][:2] == ("MATCH", False)                # the run stopped: no fallback
    # Control: the record ending the last block's own output is taken out there, and only the last line is.
    d = tmp_path / "plain"
    d.mkdir()
    (d / "t.do").write_text(f'display 5\nlocal y 2\ndisplay "{REC}"\nuse missing_part.dta\n')
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(d / "t.do"), "--cwd", str(d),
                        "--transcript", str(d / "t.tr")],
                       env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
    plain = (d / "t.tr").read_text()
    assert p.returncode == 1 and plain.split("\n").count(REC) == 2
    blocks, rec, owner = L._parse(plain, record=True)
    assert rec == REC and owner == len(blocks) - 1 and blocks[owner].key == "use missing_part.dta"
    assert REC not in blocks[owner].out and "end of do-file" not in blocks[owner].out
    assert [b.out for b in blocks if b.key.startswith("display \"")] == [[REC]]
    r = _status_rows(plain, plain, 1)
    assert r["use missing_part.dta"][:2] == ("ERROR", False)
    assert r[f'display "{REC}"'][:2] == ("MATCH", True) and r["local y 2"][:2] == ("MATCH", True)


def _case(tmp_path, monkeypatch, files, expected, tag):
    """A case whose files sit in a local cache (no network), for run_case."""
    import hashlib
    import cases as C
    cache = tmp_path / ("cache-" + tag)   # the workspace links the cached files read-only: one cache per case
    (cache / "dataverse").mkdir(parents=True)
    monkeypatch.setattr(C, "CACHE", str(cache))
    entries = []
    for fid, (path, data) in enumerate(list(files.items()) + [(None, expected)], 1):
        raw = data if isinstance(data, bytes) else data.encode()
        (cache / "dataverse" / str(fid)).write_bytes(raw)
        entries.append({"path": path, "file_id": fid, "sha256": hashlib.sha256(raw).hexdigest()})
    return {"id": "c", "source": {"doi": "local"}, "files": entries[:-1], "dofile": "t.do",
            "expected_log": entries[-1]}


def test_rules14_6_a_timeout_is_a_held_crash_through_run_case(tmp_path, monkeypatch):
    """Section 3, .14.6, through the harness entry point. A timeout has no process status: run_case tells the scorer
    the run timed out, and the scorer never reads the transcript's last line as the CLI's record. The run is a CRASH
    held by the last block, and its output, a line shaped like a stop line included, is kept as printed. Paired with
    a real CLI exit 3, where the record is the CLI's and is taken out."""
    import run as R
    do = 'display 5\nlocal y 2\ndisplay "** ose: crash: not a record"\nuse g.dta\n'
    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / "mk.do").write_text("set obs 1\ngen x = 1\nsave g.dta\n")
    (ok / "t.do").write_text(do)
    env = dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE))
    for f in ("mk.do", "t.do"):
        q = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(ok / f), "--cwd", str(ok),
                            "--transcript", str(ok / (f + ".tr"))], env=env, capture_output=True, text=True)
        assert q.returncode == 0, q.stderr
    expected = (ok / "t.do.tr").read_text()
    good_dta = (ok / "g.dta").read_bytes()
    monkeypatch.setattr(R, "PY", sys.executable)

    # A real exit 3: a file that is not a dataset makes the engine crash in `use` (an internal error; if the engine
    # later reports it as an ordinary error, pick another crash).
    case = _case(tmp_path, monkeypatch, {"t.do": do, "g.dta": b"not a dataset\n"}, expected, "crash")
    res = R.run_case(case, str(tmp_path / "w3"))
    assert res["status"] == "crash" and res["exit"] == 3
    r = {x["cmd"]: (x["cls"], bool(x["ok"]), x["why"]) for x in res["commands"]}
    assert r["use g.dta"][0] == "CRASH" and "internal error in use" in r["use g.dta"][2]
    assert r['display "** ose: crash: not a record"'][:2] == ("MATCH", True)

    # A timeout after ordinary output shaped like a stop line. The process is stood in for: the engine's own
    # transcript of the clean run, cut after that line, as a killed process leaves it, and the harness's timeout.
    cut = expected[:expected.index("** ose: crash: not a record\n") + len("** ose: crash: not a record\n")]
    real_run = subprocess.run

    def killed(cmd, **kw):
        tr = cmd[cmd.index("--transcript") + 1]
        with open(tr, "w") as f:
            f.write(cut)
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    case = _case(tmp_path, monkeypatch, {"t.do": do, "g.dta": good_dta}, expected, "timeout")
    monkeypatch.setattr(R.subprocess, "run", killed)
    res = R.run_case(case, str(tmp_path / "wt"), timeout=1)
    monkeypatch.setattr(R.subprocess, "run", real_run)
    assert res["status"] == "timeout" and res["exit"] is None
    r = {x["cmd"]: (x["cls"], bool(x["ok"]), x["why"]) for x in res["commands"]}
    shaped = 'display "** ose: crash: not a record"'
    assert r[shaped] == ("CRASH", False, "engine timed out"), r          # held: the shaped line was not taken out
    assert r["use g.dta"][:2] == ("NOT_RUN", False)
    assert r["display 5"][:2] == ("MATCH", True)
    assert r["local y 2"][:2] == ("MATCH", False)                         # its witness is the crashed row
    # The same cut transcript with a real exit 3 status: the shaped last line is read as the CLI's record.
    m = {x["cmd"]: x["cls"] for x in L.match_logs(expected, cut, exit_code=3)}
    assert m[shaped] == "CRASH"


def test_rules14_7_a_timeout_is_scored_with_its_own_transcript_only(tmp_path, monkeypatch):
    """Section 3, .14.7, through run_case with a real process timeout. The process starts, never opens its
    transcript, and is killed at the time cap. In a clean work directory it is scored with no transcript. On a retry
    in the same work directory after a successful run, the earlier run's transcript is not read: the result is the
    same, no row earns credit, and the kept transcript path holds nothing from the earlier run."""
    import run as R
    do = "display 5\nlocal y 2\ndisplay 8\ncapture log close\n"   # the last line is not counted, as in the open set
    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / "t.do").write_text(do)
    q = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(ok / "t.do"), "--cwd", str(ok),
                        "--transcript", str(ok / "t.tr")], env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)),
                       capture_output=True, text=True)
    assert q.returncode == 0, q.stderr
    expected = (ok / "t.tr").read_text()
    slow = tmp_path / "slow.sh"   # stands in for the interpreter: starts, writes nothing, outlives the time cap
    slow.write_text("#!/bin/sh\nexec sleep 30\n")
    slow.chmod(0o755)

    def timed_out(res):
        assert res["status"] == "timeout" and res["exit"] is None
        assert not any(r["ok"] or r["ok_unwitnessed"] or r["strict"] for r in res["commands"]), res["commands"]
        assert {r["cls"] for r in res["commands"]} == {"NOT_RUN"}

    case = _case(tmp_path, monkeypatch, {"t.do": do}, expected, "own")
    clean = tmp_path / "clean"
    monkeypatch.setattr(R, "PY", str(slow))
    timed_out(R.run_case(case, str(clean), timeout=1))
    assert not (clean / "c.transcript.log").exists()

    retry = tmp_path / "retry"
    monkeypatch.setattr(R, "PY", sys.executable)
    first = R.run_case(case, str(retry))
    assert first["status"] == "ok" and all(r["ok"] for r in first["commands"]), first["commands"]
    assert (retry / "c.transcript.log").read_text().startswith(". display 5")   # the kept copy of this run
    monkeypatch.setattr(R, "PY", str(slow))
    timed_out(R.run_case(case, str(retry), timeout=1))
    assert not (retry / "c.transcript.log").exists()
    assert not [p for p in os.listdir(retry) if ".run-" in p]   # each run's own directory is removed after it


def test_rules14_7_equal_error_output_is_counted_and_not_credited(tmp_path):
    """Section 3, .14.7. The engine stops at a missing file (exit 1). Against a reference with the same error output,
    the failing block is compared: the engine's failing command is the last statement of its transcript, which
    section 1 does not read, so the equal output is AMBIGUOUS with no credit. It is not ERROR. Against a reference
    whose error output differs, it is ERROR. Earlier blocks keep their credit; later ones are NOT_RUN."""
    do = tmp_path / "t.do"
    do.write_text("display 5\nuse missing_part.dta\ndisplay 8\n")
    tr = tmp_path / "t.log"
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(do), "--cwd", str(tmp_path),
                        "--transcript", str(tr)], env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)),
                       capture_output=True, text=True)
    assert p.returncode == 1, p.stderr
    actual = tr.read_text()
    lines = actual.rstrip("\n").split("\n")
    assert lines[-1].startswith("** ose: error:")
    # The same error and return-code lines, without the engine's record and its `end of do-file` footer.
    body = lines[:-1]
    while body and body[-1].strip() in ("", "end of do-file"):
        body.pop()
    assert body[-1] == "r(601);"
    same = "\n".join(body) + "\n"
    rows = {r["cmd"]: r for r in L.match_logs(same, actual, exit_code=1)}
    u = rows["use missing_part.dta"]
    assert (u["cls"], bool(u["ok"]), bool(u["ok_unwitnessed"]), u["strict"], u["echo_ambiguous"]) == \
        ("AMBIGUOUS", False, False, False, True), u
    assert (rows["display 5"]["cls"], bool(rows["display 5"]["ok"])) == ("MATCH", True)
    # A reference whose error output differs: the error line names another file; the echo is unchanged.
    out = [ln.replace("missing_part.dta", "other_part.dta") if not ln.startswith(". ") else ln for ln in body]
    other = "\n".join(out) + "\n"
    assert other != same
    rows = {r["cmd"]: r for r in L.match_logs(other, actual, exit_code=1)}
    assert rows["use missing_part.dta"]["cls"] == "ERROR" and not rows["use missing_part.dta"]["ok"]
