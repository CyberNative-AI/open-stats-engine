"""Rules 2026-11-24.2: integer exactness, decimal tolerance, failure classes, witness rule."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "harness"))
import logmatch as L  # noqa: E402


def test_integers_exact():
    # Defect in .1 found by the held-out scorer: a wrong N or df passed with +-1.
    assert L.token_cmp("1000", "1001") is None
    assert L.token_cmp("12", "13") is None
    assert L.token_cmp("1,000", "1,001") is None
    assert L.token_cmp("1,000", "1000") == "exact"


def test_decimals_last_digit():
    assert L.token_cmp(".1234", ".1235") == "approx"
    assert L.token_cmp(".1234", ".1236") is None
    assert L.token_cmp(".1234", ".12340") is None  # different printed precision
    assert L.token_cmp("1.23e+07", "1.24e+07") == "approx"
    assert L.token_cmp("1.23e+07", "1.25e+07") is None


def _log(*blocks, end=True):
    """A log of the given blocks. It ends with `. log close` (not counted) unless end=False: under .14 rule 7 an echo
    with no echo after it may be the last statement of a do-file, which is not read."""
    out = []
    for cmd, lines in blocks:
        out.append(". " + cmd)
        out.extend(lines)
        out.append("")
    if end:
        out += [". log close", ""]
    return "\n".join(out)


def test_wrong_and_not_run_after_stop():
    exp = _log(("count", ["  10"]), ("frob x", ["  3"]), ("count", ["  10"]))
    act = _log(("count", ["  10"]), ("frob x", ["ose: not implemented: command frob", "r(199);", "",
                                                 "end of do-file", "** ose: unsupported: frob"]), end=False)
    rows = L.match_logs(exp, act, exit_code=2)
    assert [r["cls"] for r in rows] == ["MATCH", "UNSUPPORTED", "NOT_RUN"]
    s = L.summarize(rows)
    assert s["matched"] == 1 and s["commands"] == 3


def test_wrong_output():
    rows = L.match_logs(_log(("count", ["  10"])), _log(("count", ["  11"])), exit_code=0)
    assert rows[0]["cls"] == "WRONG" and not rows[0]["ok"]


def test_witness_rule():
    exp = _log(("gen y = 1", []), ("count", ["  10"]))
    good = L.match_logs(exp, _log(("gen y = 1", []), ("count", ["  10"])), exit_code=0)
    assert [r["ok"] for r in good] == [True, True]
    bad = L.match_logs(exp, _log(("gen y = 1", []), ("count", ["  9"])), exit_code=0)
    assert bad[0]["cls"] == "MATCH" and bad[0]["ok"] is False and bad[0]["ok_unwitnessed"] is True


def test_volatile_and_settings():
    exp = _log(("set more off", []), ("version 16", []), ("display c(current_date)", ["24 Nov 2026"]),
               ("gen u = runiform()", []), ("count", ["  10"]))
    rows = L.match_logs(exp, _log(("count", ["  10"])), exit_code=0)
    assert [r["excluded"] for r in rows] == ["clock", "rng", None]
    s = L.summarize(rows)
    assert s["commands"] == 1 and s["excluded_clock"] == 1 and s["excluded_rng"] == 1


def test_paths_align_by_basename():
    exp = _log(('use "C:\\Users\\me\\proj\\data\\final.dta", clear', []), ("count", ["  10"]))
    act = _log(('use "/tmp/ws/data/final.dta", clear', []), ("count", ["  10"]))
    rows = L.match_logs(exp, act, exit_code=0)
    assert all(r["ok"] for r in rows)


def test_rng_only_in_command_position():
    assert L.volatile("regress y x if sample==1") is None
    assert L.volatile("bootstrap, reps(50): regress y x") == "rng"
    assert L.volatile("by g: sample 10") == "rng"
    assert L.volatile("gen z = invnormal(p)") is None


def test_tempfile_note_wrap_is_joined_on_both_sides():
    # Rules .6: invented paths. The author-side note wraps because of its path length; the engine prints it whole.
    exp = _log(("save `t', replace", ["(file /tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001 not",
                                      "    found)",
                                      "file /tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001 saved",
                                      "    as .dta format"]))
    act = _log(("save `t', replace", ["(file /w/x/ose9abc.tmp not found)",
                                      "file /w/x/ose9abc.tmp saved as .dta format"]))
    rows = L.match_logs(exp, act, exit_code=0)
    assert rows[0]["cls"] == "MATCH" and rows[0]["strict"] is True
    # the words are still compared: the plain form is a miss
    bad = L.match_logs(exp, _log(("save `t', replace", ["(file /w/x/ose9abc.tmp not found)",
                                                        "file /w/x/ose9abc.tmp saved"])), exit_code=0)
    assert bad[0]["cls"] == "WRONG"


def test_indented_lines_without_a_tempfile_are_not_joined():
    lines = ["file data/out.dta saved", "    as .dta format", "Group  |", "    abc  12"]
    assert L.join_tempfile_notes(lines) == lines
    assert L.join_tempfile_notes(["(file /q/St1.000002 not", "     found)"]) == ["(file /q/St1.000002 not", "     found)"]


def test_only_complete_save_notes_are_joined():
    # Rules .7: the join applies to the two save notes only, and only when the joined text is one complete note.
    t = "/tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001"
    assert L.join_tempfile_notes([f"file {t} saved", "    as .dta format"]) == [f"file {t} saved as .dta format"]
    assert L.join_tempfile_notes([f"(file {t}", "    not", "    found)"]) == [f"(file {t} not found)"]
    keep = [
        [t, "    12.5"],                                   # a path printed by display, then a separate result
        [f"file {t} saved", "    12.5"],                   # a complete note, then a separate result
        [f"(file {t} not", "    found) 7"],                # joined text is not exactly a note
        [f"file {t} saved", "    as .csv format"],         # other wording
        [f"note: {t} not", "    found)"],                  # not a save note
        [f"(file {t}", "    not", "    really", "    found)"],  # more than two continuation lines
    ]
    for lines in keep:
        assert L.join_tempfile_notes(lines) == lines, lines


def test_result_after_a_displayed_tempfile_path_stays_wrong():
    # A path printed by display, then a separate result line: the two lines are never joined into one.
    t = "/tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001"
    exp = _log(("display \"`t'\"", [t, "    12.5"]))
    act = _log(("display \"`t'\"", ["/w/x/ose9abc.tmp 12.5"]))
    rows = L.match_logs(exp, act, exit_code=0)
    assert rows[0]["cls"] == "WRONG"




def test_save_note_shaped_lines_from_display_are_not_joined():
    # Rules .8: the join applies to the output of a save command only. display can print a line that looks
    # like a save note; its two lines stay two lines and a one-line transcript is a miss.
    t = "/tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001"
    exp = _log(('display "file `t\' saved"', [f"file {t}", "    saved"]))
    act = _log(('display "file `t\' saved"', ["file /w/x/ose9abc.tmp saved"]))
    assert L.match_logs(exp, act, exit_code=0)[0]["cls"] == "WRONG"
    # the same lines under a save command are one note
    exp = _log(("save `t'", [f"file {t}", "    saved"]))
    act = _log(("save `t'", ["file /w/x/ose9abc.tmp saved"]))
    assert L.match_logs(exp, act, exit_code=0)[0]["cls"] == "MATCH"


def test_longer_complete_save_note_wins():
    # Rules .8: a note split before "saved" and before "as .dta format" is one note, not a shorter note plus a line.
    t = "/tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001"
    assert L.join_tempfile_notes([f"file {t}", "    saved", "    as .dta format"]) == [
        f"file {t} saved as .dta format"]
    exp = _log(("sa `t', replace", [f"file {t}", "    saved", "    as .dta format"]))
    act = _log(("sa `t', replace", ["file /w/x/ose9abc.tmp saved as .dta format"]))
    rows = L.match_logs(exp, act, exit_code=0)
    assert rows[0]["cls"] == "MATCH" and rows[0]["strict"] is True


def test_save_command_forms():
    for k in ("save `t'", "sa `t', replace", "sav x", "capture save `t'", "noisily save, replace", "save"):
        assert L.is_save_cmd(k), k
    for k in ("saveold x", "display \"save\"", "sample 10", "sum x", "save_x = 1"):
        assert not L.is_save_cmd(k), k


def test_block_comment_lines_are_not_counted():
    # Section 1 (.13): a single `/* */` that holds the whole echo is a comment; code after a closed comment counts,
    # but the scorer does not read it, so it earns no credit.
    exp = _log(("/* a note */", []), ("/* a */ sum x", ["  12"]), ("sum x", ["  12"]))
    rows = L.match_logs(exp, exp, exit_code=0)
    assert [(r["cmd"], r["cls"]) for r in rows] == [("/* a */ sum x", "AMBIGUOUS"), ("sum x", "MATCH")]


def test_echo_kinds():
    # Section 1 (.13), one echo at a time: (log lines without prefixes) -> kind, code.
    K = L.echo_kind
    assert K([""]) == ("blank", "")
    assert K(["#delimit ;"]) == ("directive", "") and K(["# d cr"]) == ("directive", "")
    assert K(["#delimit ; display 1;"])[0] == "unread"
    # certain comments
    assert K(["* a note"])[0] == "comment"
    assert K(["* a long note wrapped by the", "log at its width"])[0] == "comment"
    assert K(["* see http://example.org"])[0] == "comment"
    assert K(["// a note"])[0] == "comment"
    assert K(["/// final comment"])[0] == "comment"
    assert K(["/* one */"])[0] == "comment" and K(["/* opens", "closes */"])[0] == "comment"
    # comments the echo cannot settle: counted, never credited
    for texts in (["* a; display 1;"], ["* a ///", "display 1"], ["* a /* b */"], ["// a note", "display 2;"],
                  ["// a; display 1"], ["/* outer /* nested */ rest */"], ["/* note */ // another"],
                  ["/* a */;"], ["/* before */ * only a note"], ["///a description", "save x"], ["*/ x"]):
        assert K(texts)[0] == "unread", texts
    # plain commands
    assert K(["sum x"]) == ("plain", "sum x")
    assert K(["regress y x1 x2 x3 x4 x5, vce(cl", "uster id)"]) == ("plain", "regress y x1 x2 x3 x4 x5, vce(cluster id)")
    assert K(["lincom a-b /*p<.01*/"]) == ("plain", "lincom a-b")
    assert K(["set seed 907 // the seed"]) == ("plain", "set seed 907")
    assert K(["reg y x ///"]) == ("plain", "reg y x")
    # commands the echo cannot settle
    for texts in (["s/* join */ave x"], ["sum x /* b */, detail"], ['display "a" // b'], ["display 6//2"],
                  ['use "http://x/y.dta"'], ["reg y x ///", ", robust"], ["display 1; display 2;"], [";"],
                  ["s", "ave x"], ["reg y x // a", "note"], ["d"] * 9,
                  # .14: a ";" anywhere. It is part of the command in CR mode and closes it in ";" mode.
                  ["save x;"], ["local fixture abc;"], ["display 8;"], ["regress y x1 x2 x3 x4 x5, vce(cl", "uster id);"]):
        assert K(texts)[0] == "unread", texts


def test_every_join_must_give_the_same_kind():
    # .14: with no ";" a "> " is a wrap, so the command is the join with nothing added. The kind check stays as a
    # guard that can only take credit away (a log whose wrap lines lost their trailing blanks).
    assert L.echo_kind(["s", "ave x"])[0] == "unread"            # save, or a command named s
    assert L.echo_kind(["sa", "ve x"]) == ("plain", "save x")     # save either way (sa is save)
    assert L.echo_kind(["set m", "ore off"])[0] == "unread"      # a setting, or not
    assert L.echo_kind(["display c(current_", "date)"])[0] == "unread"
    assert L.echo_kind(["generate ab", "c = 1"]) == ("plain", "generate abc = 1")   # same kind either way


def test_unread_rows_are_counted_and_never_credited():
    blocks = [("/* outer /* nested */ rest */", []), ("/* note */ // another note", []),
              ("/* a */ sum x", ["  12"]), ("sum x /* b */, detail", ["  12"]), ("sum /* c */ x", ["  12"])]
    rows = L.match_logs(_log(*blocks), _log(*blocks), exit_code=0)
    assert [r["cmd"] for r in rows] == [b[0] for b in blocks]
    assert all(r["cls"] == "AMBIGUOUS" and r["echo_ambiguous"] and not r["ok"] and not r["ok_unwitnessed"]
               and not r["strict"] for r in rows)
    # differing output on an unread row is still WRONG
    rows = L.match_logs(_log(("sum x // b", ["  12"])), _log(("sum x // b", ["  13"])), exit_code=0)
    assert rows[0]["cls"] == "WRONG" and not rows[0]["echo_ambiguous"]   # one-line trailing comment: read
    rows = L.match_logs(_log(("sum /* c */ x", ["  12"])), _log(("sum /* c */ x", ["  13"])), exit_code=0)
    assert rows[0]["cls"] == "WRONG"


def test_credit_needs_both_sides_plain():
    # The same key can be plain on one side and not on the other (a different wrap width): no credit.
    exp = "\n".join([". // a long note that wraps ", "> at the width", ""])
    act = "\n".join([". // a long note that wraps at the width", ""])
    assert L.match_logs(exp, act, exit_code=0)[0]["cls"] == "AMBIGUOUS"
    # the author's echo is a comment: not counted, whatever the engine's echo is
    assert L.match_logs(act, exp, exit_code=0) == []


def test_silent_unread_rows_do_not_witness():
    exp = _log(("gen y = 1", []), ("sum /* c */ y", ["  1"]), ("display 2", ["2"]))
    rows = L.match_logs(exp, exp, exit_code=0)
    assert [(r["cls"], r["ok"]) for r in rows] == [("MATCH", False), ("AMBIGUOUS", False), ("MATCH", True)]


def test_save_after_a_comment_is_not_joined():
    # .13: the 8.1 join needs a plain save; a commented save is not read and its notes are compared as printed.
    t = "/tmp/a1/b2/c3/d4/e5/f6/g7/h8/i9/j10/k11/l12/St123.000001"
    for cmd in ("/* keep */ save `t'", "capture /* q */ save `t'"):
        exp = _log((cmd, [f"file {t}", "    saved", "    as .dta format"]))
        act = _log((cmd, ["file /w/x/ose9abc.tmp saved as .dta format"]))
        rows = L.match_logs(exp, act, exit_code=0)
        assert rows[0]["cls"] == "WRONG" and not rows[0]["ok"], cmd
    exp = _log(("save `t'", [f"file {t}", "    saved", "    as .dta format"]))
    act = _log(("save `t'", ["file /w/x/ose9abc.tmp saved as .dta format"]))
    rows = L.match_logs(exp, act, exit_code=0)
    assert rows[0]["cls"] == "MATCH" and rows[0]["strict"] is True
