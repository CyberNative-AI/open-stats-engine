"""Dataset combination through the interpreter and the transcript CLI."""
import io
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ENGINE = Path(__file__).resolve().parents[2] / "engine"
sys.path.insert(0, str(ENGINE))

from ose import commands  # noqa: E402,F401
from ose import missing as M  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta, read_dta  # noqa: E402
from ose.errors import StataError  # noqa: E402
from ose.interp import Interp  # noqa: E402


def column(name, kind, values, **kwargs):
    return Variable(name, kind, np.array(values, dtype=object if kind.startswith("str") else float), **kwargs)


def session(tmp_path, master, using):
    for name, dataset in using.items():
        write_dta(dataset, tmp_path / name)
    it = Interp(cwd=str(tmp_path), out=io.StringIO())
    it.ds = master
    return it


def values(it, name):
    return it.ds.find(name, abbrev=False).data.tolist()


def run_cli(tmp_path, source):
    dofile = tmp_path / "case.do"
    transcript = tmp_path / "case.log"
    dofile.write_text(source)
    run = subprocess.run(
        [sys.executable, "-m", "ose", "run", str(dofile), "--cwd", str(tmp_path), "--transcript", str(transcript)],
        env=dict(os.environ, PYTHONPATH=str(ENGINE), TMPDIR=str(tmp_path)),
        capture_output=True, text=True, check=False,
    )
    return run.returncode, transcript.read_text()


@pytest.mark.parametrize("cardinality", ["1:1", "m:1", "1:m"])
def test_merge_union_order_and_match_codes(tmp_path, cardinality):
    master_ids = [4, 1, 2] + ([4] if cardinality == "m:1" else [])
    using_ids = [4, 3, 2] + ([4] if cardinality == "1:m" else [])
    master = Dataset([column("id", "int", master_ids), column("master_x", "byte", range(len(master_ids)))])
    using = Dataset([column("using_x", "str1", ["a", "b", "c"] + (["d"] if len(using_ids) == 4 else [])),
                     column("id", "int", using_ids)])
    it = session(tmp_path, master, {"lookup table.dta": using})

    it.dispatch(f'merge {cardinality} id using "lookup table", gen(source)')

    assert it.ds.names() == ["id", "master_x", "using_x", "source"]
    assert it.ds.sortedby == ["id"]
    assert values(it, "id") == [1, 2, 3, 4] + ([4] if cardinality != "1:1" else [])
    assert values(it, "source") == [1, 3, 2, 3] + ([3] if cardinality != "1:1" else [])
    assert values(it, "master_x") == [1, 2, M.SYSMISS, 0] + ({"m:1": [3], "1:m": [0]}.get(cardinality, []))
    assert values(it, "using_x") == ["", "c", "b", "a"] + ({"m:1": ["a"], "1:m": ["d"]}.get(cardinality, []))
    mark = it.ds.var("source")
    assert mark.type == "byte"
    assert it.ds.value_labels[mark.vlabel] == {1: "Master only (1)", 2: "Using only (2)", 3: "Matched (3)"}
    assert "(_merge" not in it.transcript.getvalue()
    assert "(source==1)" in it.transcript.getvalue()


def test_composite_keys_merge_extended_missing_codes_separately(tmp_path):
    master = Dataset([column("id", "byte", [1, 1, 1, 2]),
                      column("when", "double", [M.EXT["b"], M.EXT["a"], M.SYSMISS, M.SYSMISS])])
    using = Dataset([column("id", "byte", [2, 1, 1]), column("when", "byte", [M.SYSMISS, M.SYSMISS, M.EXT["b"]])])
    it = session(tmp_path, master, {"right.dta": using})

    it.dispatch("merge 1:1 id when using right, noreport")

    assert values(it, "when") == [M.SYSMISS, M.EXT["a"], M.EXT["b"], M.SYSMISS]
    assert values(it, "_merge") == [3, 1, 3, 3]
    assert it.transcript.getvalue() == ""


@pytest.mark.parametrize(("cardinality", "side"), [("1:1", "master"), ("1:m", "master"), ("m:1", "using")])
def test_merge_duplicate_unique_side_leaves_master_unchanged(tmp_path, cardinality, side):
    master = Dataset([column("id", "byte", [1, 1] if side == "master" else [1])])
    using = Dataset([column("id", "byte", [2, 2] if side == "using" else [2])])
    it = session(tmp_path, master, {"right.dta": using})

    with pytest.raises(StataError, match=rf"uniquely identify observations in the {side} data") as error:
        it.dispatch(f"merge {cardinality} id using right, keep(match)")
    assert error.value.rc == 459
    assert it.ds is master


def test_merge_assert_is_checked_before_keep(tmp_path):
    it = session(tmp_path, Dataset([column("id", "byte", [1, 2])]),
                 {"right.dta": Dataset([column("id", "byte", [2, 3])])})

    with pytest.raises(StataError) as error:
        it.dispatch("merge 1:1 id using right, assert(match) keep(match) noreport")

    assert error.value.rc == 9
    assert values(it, "_merge") == [1, 3, 2]


def test_merge_keepusing_and_nogenerate_report_kept_rows(tmp_path):
    it = session(tmp_path, Dataset([column("id", "byte", [1, 2])]),
                 {"right.dta": Dataset([column("id", "byte", [2, 3]), column("included", "byte", [9, 8]),
                                        column("other", "byte", [6, 7])])})
    it.dispatch("merge m:1 id using right, keepusing(incl*) keep(3) assert(master match using) nogen")
    assert it.ds.names() == ["id", "included"]
    assert values(it, "included") == [9]
    lines = it.transcript.getvalue().splitlines()
    assert lines[3].split() == ["Not", "matched", "0"]
    assert lines[4].split() == ["Matched", "1"]


@pytest.mark.parametrize("replace", [False, True])
def test_merge_update_and_replace_conflict_takes_priority(tmp_path, replace):
    master = Dataset([column("id", "byte", [1, 2, 3, 4, 5]), column("score", "byte", [M.SYSMISS, 1, 2, 3, 4]),
                      column("text", "str1", ["x", "", "p", "q", "r"])])
    right = Dataset([column("id", "byte", [1, 2, 3, 4, 6]), column("score", "byte", [9, 7, 2, M.SYSMISS, 8]),
                     column("text", "str4", ["x", "new", "p", "", "last"])])
    it = session(tmp_path, master, {"right.dta": right})

    it.dispatch("merge 1:1 id using right, update noreport" + (" replace" if replace else ""))

    assert values(it, "_merge") == [4, 5, 3, 3, 1, 2]
    assert values(it, "score") == [9, 7 if replace else 1, 2, 3, 4, 8]
    assert values(it, "text") == ["x", "new", "p", "q", "r", "last"]
    assert it.ds.var("text").type == "str4"
    assert it.ds.value_labels[it.ds.var("_merge").vlabel][5] == "Nonmissing conflict (5)"


def test_merge_sorted_validates_each_side(tmp_path):
    master = Dataset([column("id", "byte", [1, 2])])
    unsorted = Dataset([column("id", "byte", [3, 1])])
    it = session(tmp_path, master, {"right.dta": unsorted})

    with pytest.raises(StataError, match="using data not sorted") as error:
        it.dispatch("merge 1:1 id using right, sorted")
    assert error.value.rc == 5
    assert it.ds is master

    it.dispatch("merge 1:1 id using right")
    assert values(it, "id") == [1, 2, 3]


def test_merge_master_metadata_and_using_options(tmp_path):
    master = Dataset([column("id", "byte", [1]), column("x", "byte", [8], label="Master label", vlabel="levels")],
                     label="Master dataset", value_labels={"levels": {8: "High"}},
                     chars={"_dta": {"note0": "1", "note1": "master"}})
    right = Dataset([column("id", "byte", [2]), column("x", "byte", [8], label="Using label", vlabel="levels"),
                     column("z", "byte", [1], label="Using-only", vlabel="z_levels")],
                    value_labels={"levels": {8: "Other"}, "z_levels": {1: "One"}},
                    chars={"_dta": {"note0": "1", "note1": "using"}, "z": {"note0": "1", "note1": "using variable"}})
    it = session(tmp_path, master, {"right.dta": right})

    it.dispatch("merge 1:1 id using right, nolabel nonotes nogen")

    assert it.ds.label == "Master dataset"
    assert it.ds.var("x").label == "Master label"
    assert it.ds.var("z").label == "Using-only"
    assert it.ds.value_labels == {"levels": {8: "High"}}
    assert it.ds.chars["_dta"] == {"note0": "1", "note1": "master"}
    assert it.ds.chars.get("z", {}) == {}

    it.ds = master
    it.dispatch("merge 1:1 id using right")
    assert it.ds.value_labels["levels"] == {8: "High"}
    assert it.ds.value_labels["z_levels"] == {1: "One"}
    assert it.ds.chars["_dta"] == {"note0": "2", "note1": "master", "note2": "using"}
    assert it.ds.chars["z"]["note1"] == "using variable"


def test_merge_force_never_coerces_keys(tmp_path):
    master = Dataset([column("id", "byte", [1]), column("x", "str2", ["ok"])])
    right = Dataset([column("id", "byte", [2]), column("x", "byte", [9])])
    wrong_keys = Dataset([column("id", "str1", ["1"])])
    it = session(tmp_path, master, {"right.dta": right, "wrong.dta": wrong_keys})

    for cmd in ("merge 1:1 id using right", "merge 1:1 id using wrong, force"):
        with pytest.raises(StataError) as error:
            it.dispatch(cmd)
        assert error.value.rc == 106
        assert it.ds is master

    it.dispatch("merge 1:1 id using right, force noreport")
    assert values(it, "x") == ["ok", ""]


def test_append_multiple_files_through_cli_and_dta_roundtrip(tmp_path):
    datasets = {
        "master.dta": Dataset([column("id", "byte", [2, 1]), column("name", "str24", ["x", "y"]),
                               column("score", "long", [16777217, 42], label="Master score", vlabel="scores")],
                              label="Master", value_labels={"scores": {42: "forty-two"}}),
        "more records.dta": Dataset([column("name", "str25", ["z"]), column("id", "int", [200]),
                                      column("score", "float", [0.25]), column("extra", "byte", [5])]),
        "end.dta": Dataset([column("id", "int", [201]), column("name", "str93", ["w"]),
                            column("ignored", "byte", [7]), column("extra", "byte", [6])]),
    }
    for name, dataset in datasets.items():
        write_dta(dataset, tmp_path / name)
    code, out = run_cli(
        tmp_path, 'use master\nappend using "more records" end, gen(file) keep(id name score extra)\n'
        'count if file == 1 & extra == 5\nsave appended\n',
    )
    assert code == 0, out
    # HNPXO1 06_citydev.log witnesses both widening notices in file order.
    assert [line for line in out.splitlines() if line.startswith("(variable name was ")] == [
        "(variable name was str24, now str25 to accommodate using data's values)",
        "(variable name was str25, now str93 to accommodate using data's values)",
    ]
    assert ". count if file == 1 & extra == 5\n  1\n" in out
    ds = read_dta(tmp_path / "appended.dta")
    assert ds.names() == ["id", "name", "score", "extra", "file"]
    assert [var.type for var in ds.vars] == ["int", "str93", "double", "byte", "byte"]
    assert ds.var("id").data.tolist() == [2, 1, 200, 201]
    assert ds.var("score").data.tolist() == [16777217, 42, 0.25, M.SYSMISS]
    assert ds.var("extra").data.tolist() == [M.SYSMISS, M.SYSMISS, 5, 6]
    assert ds.var("file").data.tolist() == [0, 0, 1, 2]
    assert ds.var("score").label == "Master score"
    assert ds.label == "Master"
    assert ds.value_labels["scores"] == {42: "forty-two"}
    assert ds.sortedby == []


def test_append_force_keep_nolabel_and_empty_master(tmp_path):
    left = Dataset([column("x", "str2", ["hi"]), column("left_only", "byte", [1])],
                   label="First file", value_labels={"first": {1: "One"}})
    right = Dataset([column("x", "byte", [5]), column("right_only", "str1", ["a"])],
                    value_labels={"second": {5: "Five"}})
    it = session(tmp_path, Dataset(), {"left.dta": left, "right.dta": right})

    with pytest.raises(StataError) as error:
        it.dispatch("append using left right")
    assert error.value.rc == 106
    assert it.ds.names() == []

    it.dispatch("append using left right, force gen(src) nolabel keep(x right_only)")
    assert it.ds.names() == ["x", "right_only", "src"]
    assert it.ds.label == "First file"
    assert values(it, "x") == ["hi", ""]
    assert values(it, "right_only") == ["", "a"]
    assert values(it, "src") == [1, 2]
    assert it.ds.value_labels == {}


def test_tempfile_merge_append_through_preserve_restore(tmp_path):
    code, out = run_cli(
        tmp_path, "set obs 2\ngen id = _n\ntempfile data\npreserve\ngen amount = id * 10\n"
        "save `data'\nrestore\nmerge 1:1 id using `data', assert(match) nogen\n"
        "append using `data', gen(source)\ncount if source == 1 & amount == 20\n",
    )
    assert code == 0, out
    assert ". count if source == 1 & amount == 20\n  1\n" in out


def test_update_without_report_evidence_exits_unsupported(tmp_path):
    write_dta(Dataset([column("id", "byte", [1]), column("x", "byte", [7])]), tmp_path / "right.dta")
    code, out = run_cli(tmp_path, "set obs 1\ngen id = 1\ngen x = .\nmerge 1:1 id using right, update\ncount\n")
    assert code == 2, out
    assert out.splitlines()[-1] == "** ose: unsupported: merge"
    assert ". count" not in out


@pytest.mark.parametrize(("command", "name"), [
    ("capture merge m:m id using right", "merge"),
    ("merge m:1 id using right, unimplemented", "merge"),
    ("append using right, unimplemented", "append"),
])
def test_combine_unsupported_exit_contract(tmp_path, command, name):
    code, out = run_cli(tmp_path, command + "\ncount\n")
    assert code == 2, out
    assert out.splitlines()[-1] == f"** ose: unsupported: {name}"
    assert ". count" not in out
