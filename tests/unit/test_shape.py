"""Data-shaping checks with hand-computed results and an opt-in published-block replay."""
import io
import math
import os
import random
import sys
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))

from ose import commands  # noqa: E402,F401
from ose import missing as M  # noqa: E402
from ose.errors import StataError, Unsupported  # noqa: E402
from ose.dataset import Dataset, Variable  # noqa: E402
from ose.dta import write_dta  # noqa: E402
from ose.interp import Interp  # noqa: E402

import numpy as np  # noqa: E402


def run(src, tmp_path):
    p = tmp_path / "t.do"
    p.write_text(src)
    out = io.StringIO()
    it = Interp(cwd=str(tmp_path), out=out)
    it.run_file(str(p))
    return it, out.getvalue()


def col(it, name):
    return [None if v >= M.SYSMISS else float(v) for v in it.ds.find(name).data]


def save(tmp_path, name, cols):
    """Write a .dta from {name: (type, [values, None for missing])}."""
    vs = [Variable(n, t, np.array([M.SYSMISS if v is None else float(v) for v in vals], dtype=np.float64))
          for n, (t, vals) in cols.items()]
    write_dta(Dataset(vs), str(tmp_path / name))


@pytest.fixture(autouse=True)
def base_data(tmp_path):
    save(tmp_path, "base.dta", {"g": ("byte", [2, 1, 1, 2, 2]), "x": ("float", [1, 4, 2, None, 7]),
                                "y": ("float", [10, None, 30, 40, 50])})


SETUP = "use base, clear\n"


def test_collapse_default_mean_by_group(tmp_path):
    it, _ = run(SETUP + "collapse x y, by(g)\n", tmp_path)
    assert it.ds.names() == ["g", "x", "y"]
    assert col(it, "g") == [1, 2]                       # sorted by the by-variable
    assert col(it, "x") == [3, 4]                       # (4+2)/2, (1+7)/2: missing ignored
    assert col(it, "y") == [30, pytest.approx(100 / 3, rel=1e-6)]
    assert it.ds.find("x").label == "(mean) x"
    assert it.ds.find("x").type == "float"
    assert it.ds.sortedby == ["g"]


def test_collapse_stats_and_targets(tmp_path):
    it, _ = run(SETUP + "collapse (sum) sx=x (count) n=x (min) lo=x (max) hi=x (firstnm) fy=y "
                        "(last) ly=y (sd) sdx=x (median) mx=x, by(g)\n", tmp_path)
    assert col(it, "sx") == [6, 8]
    assert col(it, "n") == [2, 2]
    assert it.ds.find("n").type == "long" and it.ds.find("sx").type == "double"
    assert col(it, "lo") == [2, 1] and col(it, "hi") == [4, 7]
    assert col(it, "fy") == [30, 10]          # g==1 rows in data order: y = ., 30
    assert col(it, "ly") == [30, 50]
    assert col(it, "sdx")[0] == pytest.approx(math.sqrt(2), rel=1e-6)
    assert col(it, "mx") == [3, 4]


def test_collapse_no_by_if_and_wildcards(tmp_path):
    it, _ = run(SETUP + "collapse (count) x y if g == 2\n", tmp_path)
    assert it.ds.N == 1 and col(it, "x") == [2] and col(it, "y") == [3]


def test_collapse_cw_and_empty_group_values(tmp_path):
    it, _ = run(SETUP + "collapse (mean) x (sum) y, by(g) cw\n", tmp_path)
    # cw drops rows with x or y missing: g1 keeps (2,30); g2 keeps (1,10), (7,50)
    assert col(it, "x") == [2, 4] and col(it, "y") == [30, 60]
    it, _ = run(SETUP + "replace x = . if g == 1\ncollapse (mean) m=x (sum) s=x (count) c=x, by(g)\n",
                tmp_path)
    assert col(it, "m") == [None, 4] and col(it, "s") == [0, 8] and col(it, "c") == [0, 2]


def test_collapse_refuses_what_it_does_not_do(tmp_path):
    with pytest.raises(Unsupported):
        run(SETUP + "collapse x [fw=g], by(g)\n", tmp_path)
    with pytest.raises(StataError):
        run(SETUP + "collapse (bogus) x, by(g)\n", tmp_path)
    with pytest.raises(StataError):
        run(SETUP + "collapse x g, by(g)\n", tmp_path)


def _reference(rows, stat):
    """Group means/sums/counts written with dicts and loops only."""
    groups = {}
    for g, x in rows:
        groups.setdefault(g, []).append(x)
    out = []
    for g in sorted(groups):
        xs = [x for x in groups[g] if x is not None]
        if stat == "count":
            out.append(float(len(xs)))
        elif stat == "sum":
            out.append(float(sum(xs)))
        else:
            out.append(sum(xs) / len(xs) if xs else None)
    return out


@pytest.mark.parametrize("stat", ["mean", "sum", "count"])
def test_collapse_matches_plain_reference(tmp_path, stat):
    rnd = random.Random(7)
    rows = [(rnd.randint(1, 9), None if rnd.random() < 0.1 else rnd.randint(-500, 500) / 4) for _ in range(400)]
    save(tmp_path, "r.dta", {"g": ("byte", [g for g, _ in rows]), "x": ("double", [x for _, x in rows])})
    it, _ = run(f"use r, clear\ncollapse ({stat}) x, by(g)\n", tmp_path)
    got = col(it, "x")
    want = _reference(rows, stat)
    assert len(got) == len(want)
    for a, b in zip(got, want):
        assert (a is None and b is None) or a == pytest.approx(b, rel=1e-12)


def test_reshape_numeric_stubs_with_sparse_columns_and_repeat(tmp_path):
    save(tmp_path, "panel.dta", {
        "region": ("byte", [2, 1, 1]), "firm": ("byte", [1, 2, 1]),
        "x10": ("float", [21.5, 12.5, 11.5]), "x2": ("long", [210, 120, 110]),
        "y2": ("float", [2, 1, None]), "fixed": ("byte", [8, 9, 7]),
    })
    it, out = run("use panel, clear\nreshape long x y, i(region firm) j(wave)\n", tmp_path)
    assert it.ds.sortedby == ["region", "firm", "wave"]
    assert col(it, "region") == [1, 1, 1, 1, 2, 2]
    assert col(it, "firm") == [1, 1, 2, 2, 1, 1]
    assert col(it, "wave") == [2, 10] * 3
    assert col(it, "x") == [110, 11.5, 120, 12.5, 210, 21.5]
    assert col(it, "y") == [None, None, 1, None, 2, None]
    assert col(it, "fixed") == [7, 7, 9, 9, 8, 8]
    assert "(j = 2 10)" in out

    it.dispatch("reshape wide")
    assert it.ds.sortedby == ["region", "firm"]
    assert col(it, "x2") == [110, 120, 210]
    assert col(it, "x10") == [11.5, 12.5, 21.5]
    assert col(it, "y10") == [None, None, None]
    it.dispatch("reshape long")
    assert col(it, "x") == [110, 11.5, 120, 12.5, 210, 21.5]


def test_reshape_wide_string_keys_and_saved_spec(tmp_path):
    it = Interp(cwd=str(tmp_path))
    it.ds = Dataset([
        Variable("id", "str1", np.array(["b", "a", "a"], dtype=object)),
        Variable("when", "str2", np.array(["02", "02", "01"], dtype=object)),
        Variable("x", "str3", np.array(["Bee", "Aye", "Ace"], dtype=object), label="name"),
        Variable("fixed", "byte", np.array([2., 1., 1.])),
    ])
    it.dispatch("reshape wide x, i(id) j(when) string")
    assert it.ds.find("id").data.tolist() == ["a", "b"]
    assert it.ds.find("x01").data.tolist() == ["Ace", ""]
    assert it.ds.find("x02").data.tolist() == ["Aye", "Bee"]
    assert it.ds.find("x01").label == "name"
    it.dispatch("save wide")
    it.dispatch("clear")
    it.dispatch("use wide")
    it.dispatch("reshape long")
    assert it.ds.find("when").data.tolist() == ["01", "02", "01", "02"]
    assert it.ds.find("x").data.tolist() == ["Ace", "Aye", "", "Bee"]


@pytest.mark.parametrize(("data", "command", "message"), [
    ({"g": [1, 1], "x1": [2, 3]}, "reshape long x, i(g) j(k)", "uniquely identify"),
    ({"g": [1, 1], "k": [1, 1], "x": [2, 3]}, "reshape wide x, i(g) j(k)", "not unique"),
    ({"g": [1, 1], "k": [1, 2], "x": [2, 3], "fixed": [1, 2]},
     "reshape wide x, i(g) j(k)", "varies within"),
])
def test_reshape_rejects_nonunique_keys_or_varying_constants(tmp_path, data, command, message):
    save(tmp_path, "panel.dta", {k: ("byte", v) for k, v in data.items()})
    it, _ = run("use panel, clear\n", tmp_path)
    before = it.ds
    with pytest.raises(StataError, match=message) as caught:
        it.dispatch(command)
    assert caught.value.rc == 9
    assert it.ds is before


def test_reshape_refuses_out_of_scope_options(tmp_path):
    it, _ = run(SETUP, tmp_path)
    with pytest.raises(Unsupported, match="reshape options"):
        it.dispatch("reshape long x, i(g) j(k) arbitrary")
    with pytest.raises(StataError, match="first call"):
        it.dispatch("reshape long")


def _workbook_rows(path, sheet):
    """Read the two pinned worksheets for this replay. Row two is the header."""
    with ZipFile(path) as workbook:
        shared = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        strings = ["".join(si.itertext()) for si in shared]
        xml = ElementTree.fromstring(workbook.read(f"xl/worksheets/sheet{sheet}.xml"))
    rows = []
    for row in xml.findall(".//{*}row")[1:]:
        cells = []
        for cell in row:
            value = cell.findtext("{*}v")
            if value is not None:
                cells.append(strings[int(value)] if cell.get("t") == "s" else float(value))
        rows.append(cells)
    return rows


@pytest.mark.skipif(not os.environ.get("OSE_CHECK_PUBLISHED_RESHAPE"), reason="fetches open archive inputs")
def test_reshape_matches_published_hnpxo1_blocks(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "harness"))
    import cases
    import logmatch

    if "OSE_CACHE" not in os.environ:
        monkeypatch.setattr(cases, "CACHE", str(tmp_path / "source"))
    manifest = cases.load(root / "tests/cases/open/blocks/dv-HNPXO1-04_grp_d-reshape.json")
    dofile = Path(cases.fetch(manifest["dofile"])).read_text()
    workbook = cases.fetch(manifest["workbook"])
    expected = [b for b in logmatch.parse_log(cases.expected_text(manifest))
                if b.key.startswith("reshape ")]
    commands = [line for line in dofile.splitlines() if line.split(maxsplit=1)[:1] == ["reshape"]]
    assert len(commands) == len(expected) == 2
    for sheet, (cmd, block) in enumerate(zip(commands, expected), start=1):
        header, *rows = _workbook_rows(workbook, sheet)
        cols = []
        for name, values in zip(header, zip(*rows), strict=True):
            if isinstance(values[0], str):
                cols.append(Variable(name, f"str{max(map(len, values))}", np.array(values, dtype=object)))
            else:
                cols.append(Variable(name, "double", np.array(values)))
        write_dta(Dataset(cols), str(tmp_path / "worksheet.dta"))
        it, transcript = run(f"use worksheet, clear\n{cmd}\n", tmp_path)
        actual, = [b for b in logmatch.parse_log(transcript) if b.key.startswith("reshape ")]
        assert actual.key == block.key
        assert actual.out == block.out
        source_rows = sorted((row[0], row[1], int(name[1:]), value)
                             for row in rows for name, value in zip(header[2:], row[2:], strict=True))
        result_rows = list(zip(*(it.ds.find(n).data for n in ("region", "idcode", "year", "y")), strict=True))
        assert result_rows == source_rows
