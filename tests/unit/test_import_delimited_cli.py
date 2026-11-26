"""Delimited-import controls through the command line, using invented CSVs."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

ENGINE = Path(__file__).resolve().parents[2] / "engine"
LOAD = 'import delimited using "sample.csv", clear'


def run(tmp_path, csv, commands):
    (tmp_path / "sample.csv").write_bytes(csv)
    script = tmp_path / "probe.do"
    script.write_text(commands + "\n")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ENGINE), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-m", "ose", "run", str(script), "--cwd", str(tmp_path)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout + result.stderr


def test_comma_file_reads_and_summarizes(tmp_path):
    status, output = run(tmp_path, b"x\n2\n4\n6\n", LOAD + "\nsummarize x")

    assert status == 0, output
    assert "(1 vars, 3 obs)" in output
    assert any(line.split() == ["x", "|", "3", "4", "2", "2", "6"] for line in output.splitlines())


@pytest.mark.parametrize("token", [b"9007199254740993", b"9.007199254740993e15"])
def test_equivalent_integer_tokens_both_refuse(tmp_path, token):
    status, output = run(tmp_path, b"x\n" + token + b"\n", "set type double\n" + LOAD + "\ndisplay %21.0f x[1]")

    assert status == 2, output
    assert "integer field cannot be represented exactly" in output
    assert "9007199254740992" not in output


@pytest.mark.parametrize("csv", [
    b"x\ty\n2\t4\n",
    b"x;y\n2;4\n",
    b"x\ty,z\n2\t4,6\n4\t8,10\n",
    b"x;y\n2,5;4,5\n4,5;8,5\n",
])
def test_tab_or_semicolon_file_stops_before_any_column_is_made(tmp_path, csv):
    status, output = run(tmp_path, csv, LOAD + "\ndisplay 1")

    assert status == 2, output
    assert "tab or semicolon outside quotes" in output
    assert "vars," not in output


@pytest.mark.parametrize("csv, shape", [
    (b'x\n"north;south"\n', "(1 vars, 1 obs)"),
    (b'x,y\n"north;south",2\n', "(2 vars, 1 obs)"),
])
def test_quoted_semicolon_reads(tmp_path, csv, shape):
    status, output = run(tmp_path, csv, LOAD + "\ndisplay x[1]")

    assert status == 0, output
    assert shape in output
    assert "north;south" in output.split(". display", 1)[1]


def shown(output, command):
    """The text printed by the first `display` after `command`."""
    return output.split(". " + command, 1)[1].split("\n. ", 1)[0].strip()


def test_mixed_column_integer_float_cannot_hold_refuses_by_default(tmp_path):
    status, output = run(tmp_path, b"x\n16777217\n1.5\n", LOAD + "\ndisplay %21.0f x[1]")

    assert status == 2, output
    assert "integer field cannot be represented exactly as float" in output
    assert "16777216" not in output
    assert "vars," not in output


def test_mixed_column_integer_reads_under_set_type_double(tmp_path):
    status, output = run(tmp_path, b"x\n16777217\n1.5\n", "set type double\n" + LOAD + "\ndisplay %21.0f x[1]")

    assert status == 0, output
    assert "(1 vars, 2 obs)" in output
    assert shown(output, "display %21.0f x[1]") == "16777217"


def test_mixed_column_integer_float_holds_reads_by_default(tmp_path):
    status, output = run(tmp_path, b"x\n16777218\n1.5\n", LOAD + "\ndisplay %21.0f x[1]")

    assert status == 0, output
    assert "(1 vars, 2 obs)" in output
    assert shown(output, "display %21.0f x[1]") == "16777218"


# 2**127 is exact in binary32, but its bits (0x7f000000) are the first float
# missing code in a .dta file. The largest float (0x7effffff) is one step below.
@pytest.mark.parametrize("token", [b"170141183460469231731687303715884105728",
                                   b"170141173319264429905852091742258462720"])
def test_integer_at_the_float_limit_survives_save_and_reopen(tmp_path, token):
    commands = LOAD + '\nsave "kept.dta", replace\nuse "kept.dta", clear\ndisplay %40.0f x[1]'
    status, output = run(tmp_path, b"x\n" + token + b"\n", commands)

    assert status == 0, output
    assert shown(output, "display %40.0f x[1]") == token.decode()
