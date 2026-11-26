"""The browser page offers web/x-histogram.html beside x.svg for its unedited built-in example.

The companion is a hand-checked text alternative (bin edges and counts). This test reruns the
page's own example script through the engine and fails if the engine's bins ever stop matching it.
"""
import base64
import hashlib
import html
import io
import os
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from ose import commands  # noqa: E402,F401
from ose.interp import Interp  # noqa: E402

WEB = ROOT / "web"


def page_example():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    body = re.search(r'<textarea id="dofile"[^>]*>(.*?)</textarea>', page, re.S)
    return html.unescape(body.group(1))


def companion_rows():
    text = (WEB / "x-histogram.html").read_text(encoding="utf-8")
    body = re.search(r"<tbody>(.*?)</tbody>", text, re.S).group(1)
    rows = re.findall(r"<tr><th scope=\"row\">([^<]+)</th><td>([^<]+)</td><td class=\"num\">(\d+)</td></tr>", body)
    total = int(re.search(r"Total observations</th><td class=\"num\">(\d+)<", text).group(1))
    return [(Fraction(lo), Fraction(hi), int(n)) for lo, hi, n in rows], total, text


def test_companion_matches_engine_bins(tmp_path):
    src = page_example()
    assert "graph export x.svg" in src
    p = tmp_path / "example.do"
    p.write_text(src)
    it = Interp(cwd=str(tmp_path), out=io.StringIO())
    it.run_file(str(p))
    assert os.path.isfile(tmp_path / "x.svg")
    edges, heights = it.graph["edges"], it.graph["heights"]
    assert it.graph["ylab"] == "Frequency"

    rows, total, text = companion_rows()
    assert "x.svg" in text
    assert len(rows) == len(heights) == 12
    for i, (lo, hi, n) in enumerate(rows):
        assert abs(float(lo) - edges[i]) < 1e-12
        assert abs(float(hi) - edges[i + 1]) < 1e-12
        assert n == heights[i]
    assert rows[0][0] == 0 and rows[-1][1] == 11
    assert total == sum(n for *_, n in rows) == int(heights.sum()) == 100


def test_page_offers_companion_only_for_unedited_example():
    js = (WEB / "workspace.js").read_text(encoding="utf-8")
    assert 'const builtIn = name === "x.svg" && run.inputs.dofile === synthetic;' in js
    assert 'companion.href = "x-histogram.html";' in js
    assert '"x-histogram.html"' in (WEB / "build.py").read_text(encoding="utf-8")


def test_companion_carries_font_notices():
    """The download embeds the fonts, so it carries their copyright notices and the OFL 1.1 text (condition 2)."""
    text = (WEB / "x-histogram.html").read_text(encoding="utf-8")
    flat = " ".join(html.unescape(text).split())
    licence = {"Syne": "LICENSE-Syne.txt", "DMSans": "LICENSE-DM-Sans.txt", "DMMono": "LICENSE-DM-Mono.txt"}
    faces = {hashlib.sha256(p.read_bytes()).hexdigest(): p.name for p in (WEB / "atlas").glob("*.woff2")}
    embedded = re.findall(r'url\("data:font/woff2;base64,([^"]+)"\)', text)
    assert len(embedded) == 4
    for b64 in embedded:
        name = faces[hashlib.sha256(base64.b64decode(b64, validate=True)).hexdigest()]
        notice = (WEB / "atlas" / licence[name.split("-")[0]]).read_text(encoding="utf-8")
        copyright_line, ofl = notice.split("\n", 1)
        assert copyright_line.strip() in flat, name
        ofl = " ".join(ofl.split()).replace("http://scripts.sil.org/OFL", "https://scripts.sil.org/OFL")
        assert ofl in flat.replace("http://scripts.sil.org/OFL", "https://scripts.sil.org/OFL"), name
