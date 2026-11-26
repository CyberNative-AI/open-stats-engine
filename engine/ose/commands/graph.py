"""histogram and graph export.

Graphs are drawn by our own minimal renderer. The numbers (bins, start,
width, heights) follow the language's documented rules; the picture's look
is ours and is not meant to reproduce any other program's styling.
"""
import math
import os

import numpy as np

from .. import missing as M
from ..errors import StataError, Unsupported
from ..fmt import gnum
from ..interp import command
from ..syntax import opt_lookup, parse_standard, unquote
from .core import path_of
from .data import row_mask

# Styling options that change only the look of a graph. They are accepted
# and ignored by the renderer; everything else must be understood or fail.
STYLE = ("scheme() title() subtitle() xtitle() ytitle() xlabel() ylabel() xscale() yscale() xtick() ytick() "
         "graphregion() plotregion() legend() note() caption() name() saving() color() fcolor() lcolor() "
         "lwidth() lpattern() barwidth() gap() fintensity() bcolor() blcolor() blwidth() xsize() ysize() "
         "aspectratio() normopts() kdenopts() xline() yline() text() nodraw addlabels addlabopts() xmtick() "
         "ymtick() yaxis() xaxis() horizontal")


def _hist_spec(it, rest):
    p = parse_standard(rest, using=False)
    o = opt_lookup(p.options, "BIN() Width() START() Discrete DENsity FRACtion FREQuency PERCent NORMal "
                              "KDENsity by() " + STYLE)
    if "by" in o or "discrete" in o or "kdensity" in o:
        raise Unsupported("histogram option " + next(k for k in ("by", "discrete", "kdensity") if k in o))
    if p.weight:
        raise Unsupported("histogram with weights")
    names = p.varlist.split()
    if len(names) != 1:
        raise StataError("too many variables specified", 103)
    v = it.ds.find(names[0])
    if v.isstr:
        raise StataError("type mismatch", 109)
    x = v.data[row_mask(it, p)]
    x = x[x < M.SYSMISS]
    N = len(x)
    if N == 0:
        raise StataError("no observations", 2000)
    lo, hi = float(x.min()), float(x.max())
    start = float(o["start"]) if "start" in o else lo
    if start > lo:
        raise StataError("start() must be less than or equal to the minimum", 198)
    if "bin" in o and "width" in o:
        raise StataError("options bin() and width() may not be combined", 198)
    if "width" in o:
        width = float(o["width"])
        k = max(int(math.ceil((hi - start) / width)), 1)
    else:
        k = int(o["bin"]) if "bin" in o else int(min(math.sqrt(N), 10 * math.log10(N)))
        k = max(k, 1)
        width = (hi - start) / k if hi > start else 1.0
    edges = start + width * np.arange(k + 1)
    idx = np.clip(np.floor((x - start) / width).astype(int), 0, k - 1)
    counts = np.bincount(idx, minlength=k).astype(float)
    if "frequency" in o:
        heights, ylab = counts, "Frequency"
    elif "fraction" in o:
        heights, ylab = counts / N, "Fraction"
    elif "percent" in o:
        heights, ylab = 100 * counts / N, "Percent"
    else:
        heights, ylab = counts / (N * width), "Density"
    spec = {"kind": "hist", "edges": edges, "heights": heights, "ylab": ylab,
            "xlab": unquote(o["xtitle"]) if isinstance(o.get("xtitle"), str) else (v.label or v.name),
            "title": unquote(o["title"]) if isinstance(o.get("title"), str) else ""}
    if "normal" in o:
        mu, sd = float(np.mean(x)), float(np.std(x, ddof=1))
        xs = np.linspace(edges[0], edges[-1], 200)
        dens = np.exp(-0.5 * ((xs - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
        scale = {"Density": 1.0, "Frequency": N * width, "Fraction": width, "Percent": 100 * width}[ylab]
        spec["curve"] = (xs, dens * scale)
    return spec, k, start, width


@command("histogram", 4)
def cmd_histogram(it, rest):
    spec, k, start, width = _hist_spec(it, rest)
    it.graph = spec
    it.print(f"(bin={k}, start={gnum(start, 9)}, width={gnum(width, 9)})")


@command("graph", 2)
def cmd_graph(it, rest):
    w = rest.split(None, 1)
    sub = w[0] if w else ""
    arg = w[1] if len(w) > 1 else ""
    if sub == "export":
        return _export(it, arg)
    if sub in ("close", "drop"):
        return
    raise Unsupported(f"graph {sub}")


def _export(it, arg):
    p = parse_standard(arg, using=False)
    o = opt_lookup(p.options, "as() replace name() width() height() fontface() mag() cmyk()")
    fname = unquote(p.varlist.strip())
    kind = (o.get("as") or os.path.splitext(fname)[1].lstrip(".")).lower()
    if not os.path.splitext(fname)[1]:
        fname += "." + kind
    if kind not in ("pdf", "svg"):
        raise Unsupported(f"graph export as {kind}")
    g = getattr(it, "graph", None)
    if g is None:
        raise StataError("no graphs in memory", 693)
    path = path_of(it, fname)
    if os.path.exists(path) and "replace" not in o:
        raise StataError(f"file {fname} already exists", 602)
    if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
        raise StataError(f"file {fname} could not be opened", 603)
    shapes = _layout(g)
    data = _pdf(shapes) if kind == "pdf" else _svg(shapes)
    with open(path, "wb") as f:
        f.write(data)
    it.print(f"file {fname} saved as {kind.upper()} format")


# --- renderer ------------------------------------------------------------------

W_PT, H_PT = 396.0, 288.0
L, R, B, T = 52.0, 16.0, 40.0, 20.0


def _ticks(lo, hi, n=5):
    span = hi - lo if hi > lo else 1.0
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9 * span:
        out.append(round(t, 12))
        t += step
    return out


def _layout(g):
    edges, h = g["edges"], g["heights"]
    x0, x1 = float(edges[0]), float(edges[-1])
    ymax = float(max(h.max(), g["curve"][1].max() if "curve" in g else 0)) or 1.0
    ymax *= 1.05
    sx = lambda x: L + (x - x0) / (x1 - x0 or 1) * (W_PT - L - R)
    sy = lambda y: B + y / ymax * (H_PT - B - T)
    shapes = []
    for i in range(len(h)):
        shapes.append(("rect", sx(edges[i]), sy(0), sx(edges[i + 1]) - sx(edges[i]), sy(h[i]) - sy(0)))
    if "curve" in g:
        xs, ys = g["curve"]
        shapes.append(("poly", [(sx(a), sy(b)) for a, b in zip(xs, ys)]))
    shapes.append(("line", L, B, W_PT - R, B))
    shapes.append(("line", L, B, L, H_PT - T))
    for t in _ticks(x0, x1):
        shapes.append(("line", sx(t), B, sx(t), B - 4))
        shapes.append(("text", sx(t), B - 14, gnum(t, 9), "c"))
    for t in _ticks(0, ymax):
        shapes.append(("line", L, sy(t), L - 4, sy(t)))
        shapes.append(("text", L - 6, sy(t) - 3, gnum(t, 9), "r"))
    shapes.append(("text", (L + W_PT - R) / 2, 8, g["xlab"], "c"))
    shapes.append(("vtext", 12, (B + H_PT - T) / 2, g["ylab"]))
    if g.get("title"):
        shapes.append(("text", W_PT / 2, H_PT - 14, g["title"], "c"))
    return shapes


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1")


def _pdf(shapes):
    ops = ["0.5 w", "0.36 0.47 0.6 rg", "0.2 0.25 0.3 RG"]
    for s in shapes:
        if s[0] == "rect":
            ops.append(f"{s[1]:.2f} {s[2]:.2f} {s[3]:.2f} {s[4]:.2f} re B")
    ops.append("0 0 0 RG 1 w")
    for s in shapes:
        if s[0] == "poly":
            pts = s[1]
            ops.append(f"{pts[0][0]:.2f} {pts[0][1]:.2f} m " + " ".join(f"{a:.2f} {b:.2f} l" for a, b in pts[1:]) + " S")
        elif s[0] == "line":
            ops.append(f"0.5 w {s[1]:.2f} {s[2]:.2f} m {s[3]:.2f} {s[4]:.2f} l S")
    ops.append("0 0 0 rg")
    for s in shapes:
        if s[0] == "text":
            x = s[1] - (len(s[3]) * 2.2 if s[4] == "c" else (len(s[3]) * 4.4 if s[4] == "r" else 0))
            ops.append(f"BT /F1 8 Tf {x:.2f} {s[2]:.2f} Td ({_esc(s[3])}) Tj ET")
        elif s[0] == "vtext":
            ops.append(f"BT /F1 8 Tf 0 1 -1 0 {s[1]:.2f} {s[2] - len(s[3]) * 2.2:.2f} Tm ({_esc(s[3])}) Tj ET")
    content = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W_PT:.0f} {H_PT:.0f}] /Contents 4 0 R "
            f"/Resources << /Font << /F1 5 0 R >> >> >>".encode(),
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _svg(shapes):
    y = lambda v: H_PT - v
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W_PT:.0f}" height="{H_PT:.0f}" font-family="Helvetica" font-size="8">']
    for s in shapes:
        if s[0] == "rect":
            parts.append(f'<rect x="{s[1]:.2f}" y="{y(s[2] + s[4]):.2f}" width="{s[3]:.2f}" height="{s[4]:.2f}" fill="#5b7899" stroke="#333f4d" stroke-width="0.5"/>')
        elif s[0] == "poly":
            parts.append('<polyline fill="none" stroke="#000" points="' + " ".join(f"{a:.2f},{y(b):.2f}" for a, b in s[1]) + '"/>')
        elif s[0] == "line":
            parts.append(f'<line x1="{s[1]:.2f}" y1="{y(s[2]):.2f}" x2="{s[3]:.2f}" y2="{y(s[4]):.2f}" stroke="#000" stroke-width="0.5"/>')
        elif s[0] == "text":
            anchor = {"c": "middle", "r": "end"}.get(s[4], "start")
            t = s[3].replace("&", "&amp;").replace("<", "&lt;")
            parts.append(f'<text x="{s[1]:.2f}" y="{y(s[2]):.2f}" text-anchor="{anchor}">{t}</text>')
        elif s[0] == "vtext":
            t = s[3].replace("&", "&amp;").replace("<", "&lt;")
            parts.append(f'<text transform="translate({s[1]:.2f},{y(s[2]):.2f}) rotate(-90)" text-anchor="middle">{t}</text>')
    parts.append("</svg>")
    return "\n".join(parts).encode()
