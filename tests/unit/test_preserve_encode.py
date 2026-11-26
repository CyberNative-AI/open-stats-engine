"""preserve/restore (one level, auto-restore at do-file end) and encode (sorted codes, label reuse)."""
import os
import subprocess
import sys

ENGINE = os.path.join(os.path.dirname(__file__), "..", "..", "engine")


def _run(tmp_path, src):
    do = tmp_path / "t.do"
    do.write_text(src)
    tr = tmp_path / "t.log"
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(do), "--cwd", str(tmp_path),
                        "--transcript", str(tr)], env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)),
                       capture_output=True, text=True)
    return p.returncode, tr.read_text()


def test_preserve_restore(tmp_path):
    code, out = _run(tmp_path, "set obs 5\ngen x = _n\npreserve\nkeep if x > 3\ncount\nrestore\ncount\n")
    assert code == 0, out
    assert out.split(". count")[1].split()[0] == "2"
    assert out.split(". count")[2].split()[0] == "5"


def test_double_preserve_is_error(tmp_path):
    code, out = _run(tmp_path, "set obs 1\npreserve\npreserve\n")
    assert code == 1 and "already preserved" in out


def test_restore_at_do_file_end(tmp_path):
    (tmp_path / "inner.do").write_text("preserve\ndrop if _n > 1\n")
    code, out = _run(tmp_path, "set obs 4\ngen x = _n\ndo inner.do\ncount\n")
    assert code == 0, out
    assert out.split(". count")[-1].split()[0] == "4"


def test_encode(tmp_path):
    src = ('set obs 4\ngen s = "b"\nreplace s = "a" in 2\nreplace s = "" in 3\nreplace s = "c" in 4\n'
           'encode s, gen(n)\nlist n s, nolabel\n')
    src = src.replace("list n s, nolabel\n", "display n[1] n[2] n[4]\ndisplay missing(n[3])\n")
    code, out = _run(tmp_path, src)
    assert code == 0, out
    lines = [ln for ln in out.split("\n") if ln and not ln.startswith((".", ">"))]
    assert lines[-2:] == ["213", "1"]
