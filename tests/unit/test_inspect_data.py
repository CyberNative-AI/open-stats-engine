"""Generated dataset for describe and codebook."""

import io
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from ose import commands  # noqa: E402,F401
from ose import missing as M  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402
from ose.errors import Unsupported  # noqa: E402
from ose.interp import Interp  # noqa: E402


@pytest.fixture
def inspect_dataset(tmp_path, monkeypatch):
    category = Variable("long_category_name", "float", np.array([1.] * 5 + [2.] * 6 + [M.SYSMISS]),
                        "%11.0g", "Item group", "group_labels")
    sequence = Variable("sequence", "long", np.arange(1., 13.), label="Ordered values")
    text = Variable("text", "str3", np.array(["yes"] * 12, dtype=object))
    ds = Dataset([category, sequence, text], value_labels={"group_labels": {1: "First", 2: "Second"}})
    ds.sortedby = ["sequence"]
    with monkeypatch.context() as patch:
        patch.setattr("ose.dta.time.strftime", lambda fmt: "27 Apr 2020 13:25")
        write_dta(ds, tmp_path / "generated.dta")
    output = io.StringIO()
    interpreter = Interp(cwd=str(tmp_path), out=output)
    interpreter.dispatch("use generated.dta, clear")
    return interpreter, output


def test_describe_and_codebook(inspect_dataset, tmp_path):
    interpreter, output = inspect_dataset
    do = tmp_path / "generated.do"
    do.write_text("set linesize 90\ndes\ndescribe\ncodebook long_category_name sequence\n")
    interpreter.run_file(str(do))
    abbreviated, full = output.getvalue().split(". des\n", 1)[1].split(". describe\n", 1)
    full, codebook = full.split(". codebook long_category_name sequence\n", 1)
    assert abbreviated == full
    assert "Contains data from generated.dta\n Observations:            12\n" in full
    assert "    Variables:             3                  27 Apr 2020 13:25\n" in full
    assert "long_category~e float   %11.0g     group_labels\n" in full
    assert " " * 46 + "Item group\n" in full
    assert "text            str3    %3s\n" in full
    assert "Sorted by: sequence\n" in full
    assert "Range: [1,2]                         Units: 1\n" in codebook
    assert "Unique values: 2                         Missing .: 1/12\n" in codebook
    assert "    5         1  First\n" in codebook
    assert "    6         2  Second\n" in codebook
    assert "    1         .\n" in codebook
    assert "Range: [1,12]                        Units: 1\n" in codebook
    assert "Unique values: 12                        Missing .: 0/12\n" in codebook
    assert "Mean:     6.5\n" in codebook
    assert "Std. dev.: 3.60555\n" in codebook
    assert "          2       3.5       6.5       9.5        11\n" in codebook


@pytest.mark.parametrize("command", [
    "describe, short",
    "codebook sequence if sequence > 2",
    "codebook sequence, compact",
    "codebook long_category_name text",
])
def test_unwitnessed_forms_stop_without_partial_output(inspect_dataset, command):
    interpreter, output = inspect_dataset
    with pytest.raises(Unsupported):
        interpreter.dispatch(command)
    assert output.getvalue() == ""



def _linesize(ds, interpreter, size):
    interpreter.dispatch(f"set linesize {size}")


def _var(ds, name):
    return next(v for v in ds.vars if v.name == name)


@pytest.mark.parametrize("change, command", [
    (lambda ds, it: _linesize(ds, it, 80), "describe"),
    (lambda ds, it: _linesize(ds, it, 80), "codebook sequence"),
    (lambda ds, it: setattr(ds, "label", "A generated label"), "describe"),
    (lambda ds, it: ds.chars.setdefault("_dta", {}).update(note0="1", note1="generated"), "describe"),
    (lambda ds, it: setattr(_var(ds, "sequence"), "format", "%tcCCYY-NN-DD"), "describe"),
    (lambda ds, it: setattr(_var(ds, "sequence"), "data", _var(ds, "sequence").data * 10), "codebook sequence"),
    (lambda ds, it: setattr(_var(ds, "sequence"), "label", "x" * 85), "codebook sequence"),
], ids=["describe-80", "codebook-80", "data-label", "notes", "wide-format", "units-10", "long-heading"])
def test_unwitnessed_layouts_refuse(inspect_dataset, change, command):
    interpreter, output = inspect_dataset
    interpreter.dispatch("set linesize 90")
    change(interpreter.ds, interpreter)
    before = output.getvalue()
    with pytest.raises(Unsupported):
        interpreter.dispatch(command)
    assert output.getvalue() == before


def test_describe_outside_working_directory_refuses(inspect_dataset, tmp_path):
    interpreter, output = inspect_dataset
    interpreter.dispatch("set linesize 90")
    interpreter.cwd = str(tmp_path / "elsewhere")
    with pytest.raises(Unsupported):
        interpreter.dispatch("describe")
