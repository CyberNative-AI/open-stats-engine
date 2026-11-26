"""Unit tests for the engine core. Run: python -m pytest tests/unit"""
import io
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from ose import commands  # noqa: E402,F401
from ose import missing as M  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import read_dta, write_dta  # noqa: E402
from ose.fmt import gnum  # noqa: E402
from ose.interp import Interp  # noqa: E402
from ose.lexer import logical_lines  # noqa: E402


def run(src, tmp_path):
    p = tmp_path / "t.do"
    p.write_text(src)
    out = io.StringIO()
    it = Interp(cwd=str(tmp_path), out=out)
    it.run_file(str(p))
    return it, out.getvalue()


# %9.0g on values we chose: no leading zero, trailing zeros dropped, at most 8 characters of digits and point.
@pytest.mark.parametrize("x,s", [
    (0.0031416, ".0031416"), (2.718282, "2.718282"), (1.25, "1.25"), (42.125, "42.125"),
    (0.5, ".5"), (6.022141, "6.022141"), (12.34567, "12.34567"), (4096, "4096"),
])
def test_gnum(x, s):
    assert gnum(x, 9) == s


def test_missing_order():
    assert M.SYSMISS > 1e300
    assert M.EXT["a"] > M.SYSMISS and M.EXT["z"] > M.EXT["a"]
    assert M.missing_label(M.EXT["c"]) == ".c"


def test_lexer_comments_and_continuation():
    ls = logical_lines('gen x = 1 // note\nreg y x, /// split\n  robust\n* comment\n/* block\n */ di 1')
    texts = [l.text for l in ls]
    assert texts[0] == "gen x = 1"
    assert texts[1] == "reg y x, robust"
    assert texts[2] == ""
    assert texts[3] == "di 1"


def test_delimit():
    ls = logical_lines("#delimit ;\ngen x = 1;\ngen y\n = 2;\n#delimit cr\ndi 3")
    assert [l.text for l in ls if l.text and not l.text.startswith("#")] == ["gen x = 1", "gen y = 2", "di 3"]


def test_delimit_with_space_after_hash():
    # written this way in doi:10.7910/DVN/R7RYIV table6and7.do
    ls = logical_lines("# delimit ;\ngen x = 1;\n# delimit cr\ndi 3")
    assert [l.text for l in ls if l.text and not l.text.startswith("#")] == ["gen x = 1", "di 3"]


def test_generate_float_rounding_and_messages(tmp_path):
    it, out = run("set obs 3\ngen x = 0.1\ngen y = 1 if _n > 1\nreplace y = 5 if _n == 3\ncount if x == 0.1\n",
                  tmp_path)
    assert "(1 missing value generated)" in out
    assert "(1 real change made)" in out
    # float storage: 0.1 stored as float is not equal to the double 0.1
    assert "count if x == 0.1\n  0\n" in out


def test_missing_arithmetic_and_compare(tmp_path):
    it, out = run("set obs 3\ngen x = _n\nreplace x = . in 2\ngen y = x + 1\ncount if x > 100\n", tmp_path)
    y = it.ds.find("y").data
    assert y[1] == M.SYSMISS and y[0] == 2
    assert "count if x > 100\n  1\n" in out  # missing > 100 is true


def test_by_n(tmp_path):
    it, out = run("set obs 6\ngen g = ceil(_n/3)\ngen v = 7 - _n\nbysort g (v): gen k = _n\n", tmp_path)
    assert list(it.ds.find("k").data) == [1, 2, 3, 1, 2, 3]
    assert list(it.ds.find("v").data) == [4, 5, 6, 1, 2, 3]


def test_macros_and_loops(tmp_path):
    it, out = run('local a 2\nglobal B "x"\nforvalues i = 1/`a\' {\n di "$B`i\'"\n}\n'
                  'foreach v in p q {\n di "`v\'"\n}\n', tmp_path)
    assert "x1\nx2" in out and "p\nq" in out


def test_dta_roundtrip(tmp_path):
    d = Dataset([Variable("a", "byte", np.array([1.0, M.SYSMISS, M.EXT["b"]])),
                 Variable("b", "float", np.array([0.5, 1.25, M.SYSMISS])),
                 Variable("s", "str5", np.array(["x", "yz", ""], dtype=object))], label="test")
    d.value_labels = {"lab": {1: "one"}}
    d.find("a").vlabel = "lab"
    p = str(tmp_path / "t.dta")
    write_dta(d, p)
    e = read_dta(p)
    assert e.label == "test"
    assert list(e.find("a").data) == list(d.find("a").data)
    assert list(e.find("s").data) == ["x", "yz", ""]
    assert e.value_labels == {"lab": {1: "one"}}


def test_unsupported_fails_loudly(tmp_path):
    from ose.errors import StataError
    with pytest.raises(StataError):
        run("set obs 2\nnosuchcommand x\n", tmp_path)


def test_semicolon_mode_star_comments():
    # doi:10.7910/DVN/R7RYIV table6and7.do: a blank line, then a "*" comment ending at ";"
    src = "# delimit ;\nset more off;\n\n*  Building the second wave;\ngen x = 1;\n" \
          "* a comment over\n  two lines with /* inside;\ngen y = 2; * trailing;\ngen z = 3;"
    ls = logical_lines(src)
    cmds = [l.text for l in ls if l.text and not l.text.startswith("#")]
    assert cmds == ["set more off", "gen x = 1", "gen y = 2", "gen z = 3"]
    first = next(l for l in ls if l.raw and l.raw[0].startswith("*  Building"))
    assert first.raw == ["*  Building the second wave;"]


def test_semicolon_mode_echo_skips_leading_blank_lines():
    # authors' log for doi:10.7910/DVN/R7RYIV table6and7.do echoes ". collapse ..." with no blank line first
    ls = logical_lines("# delimit ;\ngen x = 1;\n\ncollapse x,\n by(y);")
    st = next(l for l in ls if l.text.startswith("collapse"))
    assert st.raw == ["collapse x,", " by(y);"] and st.lineno == 4


def test_semicolon_mode_text_after_semicolon_opens_next_echo():
    # witnessed in doi:10.7910/DVN/R7RYIV table6and7: a comment after a semicolon is echoed as the start of the next
    # command, whose own text follows on a continuation line
    ls = logical_lines("# delimit ;\nreplace a=1; /*  note */\nreplace b=2;\ngen c=3;\n")
    assert next(l for l in ls if l.text.startswith("replace a")).raw == ["replace a=1;"]
    st = next(l for l in ls if l.text.startswith("replace b"))
    assert st.raw == [" /*  note */", "replace b=2;"]
    st = next(l for l in ls if l.text.startswith("gen c"))
    assert st.raw == ["gen c=3;"]


# Census 11-25: authors' logs use `u` (153 times, 28 logs) and `so` (147, 26 logs) with no error after them.
def test_use_and_sort_short_abbreviations(tmp_path):
    run("set obs 3\ngen x = 4 - _n\nsave a\n", tmp_path)
    it, out = run("u a, clear\nso x\ndisplay x[1]\n", tmp_path)
    assert ". display x[1]\n1\n" in out


# In display/macro context _N printed 1, so a 1/`=_N' loop silently visited one row.
def test_scalar_N_is_observation_count(tmp_path):
    it, out = run(
        "set obs 9\ngen id = _n\ndisplay _N\nlocal n = _N\ndisplay `n'\n"
        "local s = 0\nforvalues i = 1/`=_N' {\nlocal s = `s' + id[`i']\n}\ndisplay `s'\n",
        tmp_path)
    assert ". display _N\n9\n" in out, out
    assert ". display `n'\n9\n" in out, out
    assert ". display `s'\n45\n" in out, out


# HNPXO1 08 and 09: a tempfile name (extension not .dta) is saved with the format suffix; replace on a file that
# does not exist yet prints a not-found note first. A .dta name prints the plain line.
def test_save_tempfile_suffix_and_not_found_note(tmp_path):
    it, out = run("set obs 2\ngen x = _n\ntempfile t u\nsave `t'\nsave `u', replace\nsave `u', replace\n"
                  "save b.dta, replace\nsave c\n", tmp_path)
    t, u = it.locals["t"], it.locals["u"]
    assert f"file {t} saved as .dta format" in out
    assert f"(file {u} not found)\nfile {u} saved as .dta format\n" in out
    assert out.count(f"(file {u} not found)") == 1          # the second replace finds the file
    assert "(file b.dta" not in out and "file b.dta saved\n" in out   # not a tempfile: no witness for the note
    assert "file c.dta saved\n" in out and "(file c.dta" not in out
