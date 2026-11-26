"""Delimited imports through the interpreter, using invented CSVs."""

import io
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))

from ose import missing as M  # noqa: E402
from ose.commands import importdelim  # noqa: E402,F401
from ose.errors import StataError, Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402


def session(tmp_path, data, name="samples.csv"):
    (tmp_path / name).write_bytes(data)
    return Interp(cwd=str(tmp_path), out=io.StringIO())


def test_import_infers_storage_types_and_excludes_missing_from_summary(tmp_path):
    it = session(tmp_path, (
        b"Small,Medium,Large,Exact decimal,Precise decimal,Text\r\n"
        b"100,101,32741,1.25,0.1,\"north, east\"\r\n"
        b"-127,-32767,-2147483647,-2.5,0.123456789,\"say \"\"yes\"\"\"\r\n"
        b",.a,.,,,\r\n"
    ), "field notes, part 1.csv")

    it.dispatch('import delimited using "field notes, part 1.csv", varnames(1)')

    assert it.transcript.getvalue().splitlines() == [
        "(encoding automatically selected: ISO-8859-1)",
        "(6 vars, 3 obs)",
    ]
    assert [v.type for v in it.ds.vars] == ["byte", "int", "long", "float", "float", "str11"]
    assert it.ds.names() == ["small", "medium", "large", "exact_decimal", "precise_decimal", "text"]
    assert it.ds.var("exact_decimal").label == "Exact decimal"
    assert it.ds.var("text").data.tolist() == ["north, east", 'say "yes"', ""]
    assert it.ds.var("small").data.tolist() == [100, -127, M.SYSMISS]
    assert it.ds.var("medium").data[2] == M.EXT["a"]
    assert it.ds.var("large").data[2] == M.SYSMISS
    assert it.ds.var("precise_decimal").data[1] == float(np.float32(0.123456789))

    it.dispatch("summarize exact_decimal, meanonly")

    assert it.r["N"] == 2
    assert it.r["mean"] == -0.625


@pytest.mark.parametrize("command", ["import delimited using rates.csv, varnames(1)",
                                     "insheet using rates.csv, comma"])
def test_decimals_take_the_session_default_type(tmp_path, command):
    # Decisions §10: under the default type, imported decimals are stored as float.
    # PXAPMY's reference zinb fits support this as numerical evidence from local
    # maxima, not a bound.
    it = session(tmp_path, b"rate,count\n0.1,3\n2.675,4\n", "rates.csv")
    it.dispatch(command)
    assert [v.type for v in it.ds.vars] == ["float", "byte"]
    assert it.ds.var("rate").data.tolist() == [float(np.float32(0.1)), float(np.float32(2.675))]

    it.dispatch("set type double")
    it.dispatch(command + ("" if "clear" in command else ", clear").replace(", clear", " clear" if "," in command else ", clear"))
    assert it.ds.var("rate").type == "double"
    assert it.ds.var("rate").data.tolist() == [0.1, 2.675]


def test_decimals_beyond_float_range_refuse_under_the_default_type(tmp_path):
    it = session(tmp_path, b"x\n1.5\n3.5e38\n", "big.csv")
    with pytest.raises(Unsupported, match="float range"):
        it.dispatch("import delimited using big.csv, varnames(1)")
    it.dispatch("set type double")
    it.dispatch("import delimited using big.csv, varnames(1)")
    assert it.ds.var("x").type == "double"


def test_insheet_normalises_names_and_keeps_text_missing_markers(tmp_path):
    it = session(tmp_path, (
        ',"Coast.Name",CoastName,2nd group\n'
        '10,"é\nété",NA,2\n'
        '15,,.,3\n'
    ).encode(), "places.csv")
    it.dispatch("insheet using places.csv, comma")

    assert it.transcript.getvalue() == "(4 vars, 2 obs)\n"
    assert it.ds.names() == ["v1", "coastname", "coastname1", "_2ndgroup"]
    assert it.ds.var("coastname").type == "str8"
    assert it.ds.var("coastname").data.tolist() == ["é\nété", ""]
    assert it.ds.var("coastname1").data.tolist() == ["NA", "."]


@pytest.mark.parametrize("source", [b"caf\xe9", "café".encode()])
def test_encoding_preserves_text(source, tmp_path):
    it = session(tmp_path, b"Product,Amount\n" + source + b",10\n")
    it.dispatch("import delimited samples.csv, varname(1)")

    assert it.ds.var("product").data.tolist() == ["café"]
    assert ("ISO-8859-1" in it.transcript.getvalue()) == (source == b"caf\xe9")


def test_bom_and_header_only_have_zero_observations(tmp_path):
    it = session(tmp_path, b'\xef\xbb\xbf"Measure",Result\n')
    it.dispatch("import delimited samples.csv")

    assert it.ds.names() == ["measure", "result"]
    assert it.transcript.getvalue() == "(2 vars, 0 obs)\n"


def test_numeric_first_record_is_data_and_empty_record_fields_are_missing(tmp_path):
    it = session(tmp_path, b"10,20\n\n,\n30,40\n")
    it.dispatch("insheet samples.csv")

    assert it.ds.names() == ["v1", "v2"]
    assert it.ds.var("v1").data.tolist() == [10, M.SYSMISS, 30]
    assert it.ds.var("v2").data.tolist() == [20, M.SYSMISS, 40]


def test_clear_is_required_for_unsaved_data(tmp_path):
    it = session(tmp_path, b"Score\n3\n")
    it.dispatch("set varabbrev off")
    it.dispatch("import delimited samples.csv")
    original = it.ds

    with pytest.raises(StataError) as exc:
        it.dispatch("insheet samples.csv")

    assert exc.value.rc == 4
    assert it.ds is original
    it.dispatch("insheet samples.csv, clear")
    assert it.ds is not original
    assert it.ds.varabbrev is False


@pytest.mark.parametrize("command", [
    "import excel samples.xlsx",
    "import delimited samples.csv, varnames(2)",
    "import delimited samples.csv, delimiters(\"|\")",
    "import delimited samples.csv, case(preserve)",
    "import delimited samples.csv, encoding(\"UTF-8\")",
    "import delimited samples.csv, stringcols(1)",
    "import delimited samples.csv, numericcols(1)",
    "import delimited samples.csv, rowrange(2:3)",
    "import delimited samples.csv, bogus",
    "insheet samples.csv, names",
    "insheet samples.csv, tab",
])
def test_unwitnessed_forms_raise_unsupported(tmp_path, command):
    it = session(tmp_path, b"Score\n3\n")

    with pytest.raises(Unsupported):
        it.dispatch(command)

    assert it.ds.vars == []
    assert it.transcript.getvalue() == ""


@pytest.mark.parametrize("malformed", [
    b"score,note\n5\n",
    b'score,note\n5,"unclosed\n',
    b"score\n\x005\n",
    b"score\n9007199254740993\n",
    b"score\n1e309\n",
])
def test_failed_import_leaves_unsaved_data_intact(tmp_path, malformed):
    it = session(tmp_path, b"Score\n3\n")
    it.dispatch("insheet samples.csv")
    original = it.ds
    before = it.transcript.getvalue()
    (tmp_path / "samples.csv").write_bytes(malformed)

    with pytest.raises(Unsupported):
        it.dispatch("import delimited samples.csv, clear")

    assert it.ds is original
    assert it.transcript.getvalue() == before


def test_insheet_keeps_a_heading_changed_only_by_case_as_the_label(tmp_path):
    # AZEOHU open case, log line 28: after insheet, a frequency table carries the
    # upper-case CSV heading of the lower-case variable. Invented CSV below.
    it = session(tmp_path, b"Q6,Rate.1,count\n1,2,3\n2,3,4\n", "survey.csv")
    it.dispatch("insheet using survey.csv, comma")
    assert it.ds.names() == ["q6", "rate1", "count"]
    assert [v.label for v in it.ds.vars] == ["Q6", "", ""]


@pytest.mark.parametrize("data", [
    b"left\tright\n7\t8\n9\t10\n",
    b"left;right\n7;8\n9;10\n",
    b"7;8\n9;10\n",
    # Commas inside the fields would otherwise split these into the wrong columns.
    b"left\tright,extra\n7\t8,9\n10\t11,12\n",
    b"left;right\n2,5;4,5\n4,5;8,5\n",
    # A comma file with a bare semicolon in a text field: the reader cannot tell
    # it from a semicolon file, so it refuses too.
    b"name,note\nalpha,one; two\n",
])
@pytest.mark.parametrize("command", ["import delimited samples.csv, clear", "insheet using samples.csv, clear"])
def test_tab_or_semicolon_outside_quotes_refuses(tmp_path, data, command):
    it = session(tmp_path, data)

    with pytest.raises(Unsupported, match="tab or semicolon outside quotes"):
        it.dispatch(command)

    assert it.ds.vars == []
    assert it.transcript.getvalue() == ""


@pytest.mark.parametrize("data, columns", [
    (b"left,right\n\"7;8\",9\n", {"left": ["7;8"], "right": [9]}),
    (b"place\n\"north;south\"\n\"east\tsouth\"\n", {"place": ["north;south", "east\tsouth"]}),
    (b"place\n\"say \"\"a;b\"\"\"\n", {"place": ['say "a;b"']}),
    (b"place,count\n\"two\nlines; here\",3\n", {"place": ["two\nlines; here"], "count": [3]}),
])
def test_tab_or_semicolon_inside_quotes_still_reads(tmp_path, data, columns):
    it = session(tmp_path, data)

    it.dispatch("import delimited samples.csv, clear")

    assert {name: it.ds.var(name).data.tolist() for name in columns} == columns


@pytest.mark.parametrize("token", [
    b"9007199254740993",
    b"9.007199254740993e15",
    b"9007199254740993e0",
    b"900719925474099.3E1",
    b"90071992547409930e-1",
    b"+9.007199254740993e+15",
    b"-9.007199254740993e15",
    b"1" + b"0" * 300,
])
@pytest.mark.parametrize("settype", [None, "set type double"])
def test_integer_beyond_binary64_refuses_in_any_notation(tmp_path, token, settype):
    it = session(tmp_path, b"id\n1\n" + token + b"\n")
    if settype:
        it.dispatch(settype)

    with pytest.raises(Unsupported, match="integer field cannot be represented exactly"):
        it.dispatch("import delimited samples.csv, clear")

    assert it.ds.vars == []


@pytest.mark.parametrize("token", [b"9007199254740992", b"9.007199254740992e15", b"9007199254740994e0",
                                   b"3.5e38", b"6.02E23", b"1e300"])
def test_integer_whose_written_digits_binary64_keeps_reads(tmp_path, token):
    it = session(tmp_path, b"id\n" + token + b"\n")
    it.dispatch("set type double")

    it.dispatch("import delimited samples.csv, clear")

    assert it.ds.var("id").data[0] == float(token)


def test_integers_beyond_long_take_float_only_inside_its_range(tmp_path):
    # 2**127 is exact in binary32 but encodes a missing value in a .dta file.
    it = session(tmp_path, b"a,b\n170141173319264429905852091742258462720,170141183460469231731687303715884105728\n",
                 "big.csv")
    it.dispatch("import delimited using big.csv, clear")
    assert [v.type for v in it.ds.vars] == ["float", "double"]
    assert it.ds.var("b").data.tolist() == [2.0**127]
