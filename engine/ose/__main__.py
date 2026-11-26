"""Command line: python -m ose run FILE.do [--cwd DIR] [--transcript PATH] [--linesize N]"""
import argparse
import os
import sys

from . import commands  # noqa: F401
from .errors import StataError, Unsupported
from .interp import Interp


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ose")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a do-file")
    r.add_argument("dofile")
    r.add_argument("--cwd", default=None, help="working directory (default: current)")
    r.add_argument("--transcript", default=None, help="write the full session output here")
    r.add_argument("--linesize", type=int, default=None,
                   help="session line width, as the author's window had it (default 80; `set linesize` overrides)")
    a = ap.parse_args(argv)
    cwd = os.path.abspath(a.cwd or os.getcwd())
    out = open(a.transcript, "w", encoding="utf-8") if a.transcript else sys.stdout
    it = Interp(cwd=cwd, out=out)
    if a.linesize is not None:
        if not 40 <= a.linesize <= 255:
            ap.error("--linesize must be between 40 and 255")
        it.settings["linesize"] = str(a.linesize)
    # Exit codes (io-contract with the held-out scorer): 0 ran to the end, 1 stopped on a
    # runtime error, 2 stopped on an unsupported command or option, 3 internal crash.
    code, last = 0, None
    try:
        it.run_file(os.path.abspath(a.dofile))
    except Unsupported as e:
        code, last = 2, "** ose: unsupported: " + (e.cmd or e.what.split()[0])
    except StataError as e:
        if e.rc == 9999:
            code, last = 3, "** ose: crash: " + _one_line(e.msg)
        else:
            code, last = 1, "** ose: error: " + _one_line(e.msg)
    except Exception as e:  # noqa: BLE001 - a bug outside dispatch; fail loudly
        code, last = 3, f"** ose: crash: {type(e).__name__}: {_one_line(str(e))}"
    finally:
        for lg in list(it.logs):
            lg.f.close()
    if last:
        out.write(last + "\n")
    if a.transcript:
        out.close()
    if it.unsupported:
        sys.stderr.write("unsupported: " + "; ".join(it.unsupported) + "\n")
    return code


def _one_line(s):
    return " ".join(str(s).split())[:200]

if __name__ == "__main__":
    sys.exit(main())
