"""io-contract with the held-out scorer: exit codes and the transcript's last line."""
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
    return p.returncode, tr.read_text().rstrip("\n").split("\n")[-1]


def test_clean_run(tmp_path):
    assert _run(tmp_path, "display 1\n")[0] == 0


def test_unsupported_not_swallowed_by_capture(tmp_path):
    code, last = _run(tmp_path, "capture frobnicate x\ndisplay 2\n")
    assert code == 2 and last == "** ose: unsupported: frobnicate"


def test_shell_refused(tmp_path):
    code, last = _run(tmp_path, "!ls\n")
    assert code == 2 and last == "** ose: unsupported: shell"


def test_runtime_error(tmp_path):
    code, last = _run(tmp_path, "display x\n")
    assert code == 1 and last.startswith("** ose: error:")


def test_unbuilt_command_under_by_is_unsupported(tmp_path):
    # Witnessed in HNPXO1 08_table8: an unbuilt command under bysort stopped with r(199) and exit 1 before this fix.
    code, last = _run(tmp_path, "set obs 2\ngen g = 1\nbysort g: frobnicate x\n")
    assert code == 2 and last.startswith("** ose: unsupported:")


def test_unbuilt_estimator_option_is_unsupported(tmp_path):
    model = ("set obs 40\ngen f = mod(_n, 4)\ngen g = mod(floor((_n - 1)/4), 5)\n"
             "gen x = mod(_n*_n, 17)\ngen y = 3*x + mod(_n*_n*_n, 11)\n"
             "reghdfe y x, absorb(f g) cluster(f)")
    assert _run(tmp_path, model + "\n")[0] == 0
    code, last = _run(tmp_path, model + " noconstant\n")
    assert code == 2 and last.startswith("** ose: unsupported:")
