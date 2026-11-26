"""The two-file merge reader example (docs/examples/merge-two-files) must keep its exact rows."""
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
EX = ROOT / "docs" / "examples" / "merge-two-files"
sys.path.insert(0, str(ENGINE))

from ose import commands  # noqa: E402,F401
from ose.interp import Interp  # noqa: E402

ROWS = """101 Ada . 1
102 Bo . 1
103 Cy . 1
104 Dev 88 3
105 Fay 77 3
106 Gus 64 3
107 Eli 59 3
203  90 2
204  83 2
"""


def test_merge_example_rows_and_counts(tmp_path):
    subprocess.run([sys.executable, "-I", str(EX / "make_inputs.py"), str(ENGINE), str(tmp_path)],
                   check=True, capture_output=True)
    exp = json.loads((tmp_path / "expected.json").read_text())
    assert (exp["matched"], exp["from_master"], exp["from_using"]) == (4, 3, 2)
    guide = (EX / "README.md").read_text()
    dofile = guide.split("## The do-file\n\n```stata\n", 1)[1].split("```", 1)[0]
    (tmp_path / "merge-two-files.do").write_text(dofile)
    out = io.StringIO()
    it = Interp(cwd=str(tmp_path), out=out)
    it.run_file(str(tmp_path / "merge-two-files.do"))
    log = out.getvalue()
    assert ROWS in log, log
    assert it.ds.N == exp["rows_after_merge"] == 9
    assert "from master                         3  (_merge==1)" in log
    assert "from using                          2  (_merge==2)" in log
    assert "Matched                                 4  (_merge==3)" in log
    # an _N-bounded loop must see the same nine rows
    out2 = io.StringIO()
    it2 = Interp(cwd=str(tmp_path), out=out2)
    p = tmp_path / "n.do"
    p.write_text('use "roster.dta", clear\nmerge 1:1 id using "scores.dta"\ndisplay _N\n'
                 'forvalues i = 1/`=_N\' {\ndisplay id[`i\'] " " name[`i\'] " " score[`i\'] " " _merge[`i\']\n}\n')
    it2.run_file(str(p))
    assert ". display _N\n9\n" in out2.getvalue()
    assert ROWS in out2.getvalue(), out2.getvalue()
