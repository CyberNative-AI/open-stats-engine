"""`log using FILE, append` adds a session after the file's text; `replace` starts the file again."""
import os
import subprocess
import sys

ENGINE = os.path.join(os.path.dirname(__file__), "..", "..", "engine")


def _run(tmp_path, name, src):
    do = tmp_path / name
    do.write_text(src)
    p = subprocess.run([sys.executable, "-s", "-m", "ose", "run", str(do), "--cwd", str(tmp_path),
                        "--transcript", str(tmp_path / (name + ".tr"))],
                       env=dict(os.environ, PYTHONPATH=os.path.abspath(ENGINE)), capture_output=True, text=True)
    return p


def test_append_keeps_the_earlier_session(tmp_path):
    assert _run(tmp_path, "a.do", "log using s.log, text replace\nlocal z 1\nlog close\n").returncode == 0
    first = (tmp_path / "s.log").read_bytes()
    assert _run(tmp_path, "b.do", "log using s.log, text append\ndisplay 8\nlog close\n").returncode == 0
    both = (tmp_path / "s.log").read_bytes()
    assert both.startswith(first) and len(both) > len(first)      # the first session is an exact prefix
    assert both[len(first):].startswith(b"-" * 20)               # a file that ends a line gets no extra blank line
    text = both.decode()
    assert text.count("opened on:") == 2 and text.count("closed on:") == 2
    # the second session reads back as a log: the scorer finds both sessions' commands and the new output
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "harness"))
    from logmatch import parse_log
    blocks = parse_log(text)
    keys = [b.key for b in blocks]
    assert "local z 1" in keys and "display 8" in keys
    assert [b.out for b in blocks if b.key == "display 8"][0] == ["8"]


def test_replace_starts_the_file_again(tmp_path):
    assert _run(tmp_path, "a.do", "log using s.log, text replace\nlocal z 1\nlog close\n").returncode == 0
    assert _run(tmp_path, "b.do", "log using s.log, text replace\ndisplay 8\nlog close\n").returncode == 0
    text = (tmp_path / "s.log").read_text()
    assert text.count("opened on:") == 1 and ". local z 1" not in text and ". display 8" in text


def test_existing_file_without_an_option_is_refused(tmp_path):
    assert _run(tmp_path, "a.do", "log using s.log, text replace\nlog close\n").returncode == 0
    before = (tmp_path / "s.log").read_bytes()
    p = _run(tmp_path, "b.do", "log using s.log, text\n")
    assert p.returncode == 1
    assert (tmp_path / "s.log").read_bytes() == before
    assert "already exists" in (tmp_path / "b.do.tr").read_text() + p.stderr


def test_append_to_a_file_whose_last_line_has_no_line_end(tmp_path):
    """A text log cut after its last result (a partly recovered file) keeps that result: append adds one line end
    before the new header and leaves the existing bytes as they were."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "harness"))
    from logmatch import parse_log
    assert _run(tmp_path, "a.do", "log using s.log, text replace\ndisplay 83\n").returncode == 0
    full = (tmp_path / "s.log").read_bytes()
    first = full[:full.index(b"\n83\n") + 3]                       # ends with "83", no line end
    (tmp_path / "s.log").write_bytes(first)
    assert [b.out for b in parse_log(first.decode()) if b.key == "display 83"][0] == ["83"]
    assert _run(tmp_path, "b.do", "log using s.log, text append\ndisplay 8\nlog close\n").returncode == 0
    both = (tmp_path / "s.log").read_bytes()
    assert both.startswith(first) and both[len(first):].startswith(b"\n" + b"-" * 20)
    blocks = parse_log(both.decode())
    assert [b.out for b in blocks if b.key == "display 83"][0] == ["83"]      # the earlier result reads as before
    assert [b.out for b in blocks if b.key == "display 8"][0] == ["8"]


def test_append_to_an_empty_file_writes_no_line_end_first(tmp_path):
    (tmp_path / "s.log").write_bytes(b"")
    assert _run(tmp_path, "b.do", "log using s.log, text append\ndisplay 8\nlog close\n").returncode == 0
    assert (tmp_path / "s.log").read_bytes().startswith(b"-" * 20)


def test_append_to_a_write_only_file_is_a_file_access_error(tmp_path):
    """Append reads the file's last byte from the file it appends to, so it needs read access. A file the caller can
    write but not read is refused as a file-access failure (exit 1, rc 603), never an internal error, and its bytes
    are left as they were."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        import pytest
        pytest.skip("root reads a mode-0200 file")
    assert _run(tmp_path, "a.do", "log using s.log, text replace\ndisplay 83\nlog close\n").returncode == 0
    before = (tmp_path / "s.log").read_bytes()
    os.chmod(tmp_path / "s.log", 0o200)
    try:
        p = _run(tmp_path, "b.do", "log using s.log, text append\ndisplay 8\n")
    finally:
        os.chmod(tmp_path / "s.log", 0o600)
    tr = (tmp_path / "b.do.tr").read_text()
    assert p.returncode == 1, tr + p.stderr
    assert "could not open log s.log" in tr and "readable and writable" in tr and "internal error" not in tr
    assert (tmp_path / "s.log").read_bytes() == before
