"""In-memory transcripts, SVG plots and CSV exports for the browser worker."""

from io import StringIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from . import commands  # noqa: F401 - register the engine's commands
from .__main__ import _one_line
from .errors import StataError, Unsupported
from .interp import Interp


def run(dofile_text: str, files: dict[str, bytes]) -> str:
    """Run a do-file and return the console transcript."""
    log, _, _, _ = _run(dofile_text, files, (), collect_svg=False)
    return log


def run_with_svg(
    dofile_text: str, files: dict[str, bytes], dirs: tuple[str, ...] = ()
) -> tuple[str, list[tuple[str, bytes]], int]:
    """Return the transcript, SVG exports and engine exit code."""
    log, graphs, _, code = _run(dofile_text, files, dirs, collect_svg=True)
    return log, graphs, code


def run_with_outputs(
    dofile_text: str, files: dict[str, bytes], dirs: tuple[str, ...] = ()
) -> tuple[str, list[tuple[str, bytes]], list[tuple[str, bytes]], int]:
    """Return the transcript, SVG plots, CSV exports and engine exit code."""
    return _run(dofile_text, files, dirs, collect_svg=True, collect_csv=True)


class InputPathError(ValueError):
    pass


def _relative_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise InputPathError("Input paths must be relative to the run directory.")
    return path


def _exports(root, files, pattern):
    exports = []
    for path in sorted(root.rglob(pattern)):
        name = path.relative_to(root).as_posix()
        if path.is_file() and name not in files:
            exports.append((name, path.read_bytes()))
    return exports


def _run(dofile_text, files, dirs, *, collect_svg, collect_csv=False):
    out = StringIO()
    with TemporaryDirectory(prefix="ose-web-") as temporary:
        root = Path(temporary)
        script = root / ".input.do"
        interpreter = Interp(cwd=temporary, out=out)
        code = 0
        graphs = []
        csvs = []
        try:
            for name in dirs:
                (root / _relative_path(name)).mkdir(parents=True, exist_ok=True)
            for name, data in files.items():
                target = root / _relative_path(name)
                if target == script:
                    raise InputPathError("Input path is reserved for the do-file.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

            script.write_text(dofile_text, encoding="utf-8")
            interpreter.run_file(script)
            if collect_svg:
                graphs = _exports(root, files, "*.svg")
            if collect_csv:
                csvs = _exports(root, files, "*.[cC][sS][vV]")
        except Unsupported as exc:
            code = 2
            out.write("** ose: unsupported: " + (exc.cmd or exc.what.split()[0]) + "\n")
        except (StataError, InputPathError) as exc:
            message = exc.msg if isinstance(exc, StataError) else exc
            code = 3 if getattr(exc, "rc", None) == 9999 else 1
            status = "crash" if code == 3 else "error"
            out.write(f"** ose: {status}: {_one_line(message)}\n")
        except Exception as exc:  # follow the CLI's crash contract
            code = 3
            out.write(f"** ose: crash: {type(exc).__name__}: {_one_line(exc)}\n")
        finally:
            for log in interpreter.logs:
                log.f.close()
    if code != 0:
        return out.getvalue(), [], [], code
    return out.getvalue(), graphs, csvs, code
