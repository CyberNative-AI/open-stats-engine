"""Metadata and numeric summaries witnessed in the 9N6PBH author log."""

import os
from math import gcd
from textwrap import wrap

import numpy as np

from .. import missing as M
from ..errors import Unsupported
from ..fmt import gnum
from ..interp import command
from ..syntax import parse_standard
from .summ import moments, pctile, wrap_title


# Only linesize 90 is witnessed (9N6PBH); other widths change rules and wrapping.
WITNESSED_LINESIZE = 90


@command("describe", 3)
def cmd_describe(it, rest):
    ds = it.ds
    width = it.linesize()
    if rest or not ds.filename or ds.changed:
        raise Unsupported("describe requires a bare command and an unchanged file-backed dataset")
    if width != WITNESSED_LINESIZE:
        raise Unsupported("describe at a line width other than the witnessed 90")
    if os.path.dirname(os.path.abspath(ds.filename)) != os.path.abspath(it.cwd):
        raise Unsupported("describe of a file outside the working directory")
    if ds.label or ds.notes or any(k.startswith("note") for c in ds.chars.values() for k in c):
        raise Unsupported("describe of a dataset with a label or notes")
    if any(len(var.format) > 10 for var in ds.vars):
        raise Unsupported("describe with a display format wider than its column")

    rule = "-" * width
    it.print("")
    it.print(f"Contains data from {os.path.basename(ds.filename)}")
    it.print(f" Observations:{ds.N:>14,}")
    it.print(f"    Variables:{len(ds.vars):>14,}{'':18}{ds.timestamp}".rstrip())
    it.print(rule)
    it.print("Variable      Storage   Display    Value")
    it.print("    name         type    format    label      Variable label")
    it.print(rule)
    for var in ds.vars:
        name = var.name if len(var.name) <= 15 else var.name[:13] + "~" + var.name[-1]
        left = f"{name:<16}{var.type:<8}{var.format:<11}{var.vlabel:<11}"
        labels = wrap(var.label, width, initial_indent=" " * 46, subsequent_indent=" " * 48)
        if labels and len(var.vlabel) < 10:
            it.print(left + labels[0][46:])
            labels = labels[1:]
        else:
            it.print(left.rstrip())
        for line in labels:
            it.print(line)
    it.print(rule)
    it.print(("Sorted by: " + " ".join(ds.sortedby)).rstrip())


@command("codebook")
def cmd_codebook(it, rest):
    p = parse_standard(rest)
    width = it.linesize()
    if not p.varlist or p.if_ or p.in_ or p.weight or p.using or p.opt_text or p.exp is not None:
        raise Unsupported("codebook requires a numeric variable list")
    if width != WITNESSED_LINESIZE:
        raise Unsupported("codebook at a line width other than the witnessed 90")

    names = it.ds.expand_varlist(p.varlist.split())
    blocks = [_codebook_lines(it.ds, it.ds.find(name), width) for name in names]
    for block in blocks:
        for line in block:
            it.print(line)


def _codebook_lines(ds, var, width):
    if var.isstr or np.any(var.data > M.SYSMISS):
        raise Unsupported(f"codebook storage or missing values for {var.name}")
    values = var.data[var.data < M.SYSMISS]
    levels, counts = np.unique(values, return_counts=True)
    if not len(levels) or np.any(levels != np.floor(levels)):
        raise Unsupported(f"codebook requires observed integer-valued data for {var.name}")
    if gcd(*(int(v) for v in levels)) != 1:
        raise Unsupported(f"codebook units other than 1 for {var.name}")
    if len(var.name) + 1 + len(var.label) > width:
        raise Unsupported(f"codebook heading wider than the line for {var.name}")
    categorical = len(levels) <= 9
    labels = ds.value_labels.get(var.vlabel, {})
    if categorical and any(value not in labels for value in levels):
        raise Unsupported(f"codebook requires labels for each category of {var.name}")
    if not categorical and var.vlabel:
        raise Unsupported(f"codebook summary of labeled data for {var.name}")

    missing = ds.N - len(values)
    rule = "-" * width
    spacing = max(width - len(var.label), len(var.name) + 1)
    lines = ["", rule, f"{var.name:<{spacing}}{var.label}".rstrip(), rule, "",
             f"{'Type:':>23} Numeric ({var.type})"]
    if categorical:
        lines.append(f"{'Label:':>23} {var.vlabel}")
    range_text = f"[{gnum(levels[0])},{gnum(levels[-1])}]"
    lines.extend([
        "",
        f"{'Range:':>23} {range_text:<25}{'Units:':>11} 1",
        f"{'Unique values:':>23} {len(levels):<25,}{'Missing .:':>11} {missing:,}/{ds.N:,}",
        "",
    ])
    if categorical:
        lines.append("            Tabulation: Freq.   Numeric  Label")
        for value, count in zip(levels, counts):
            label, *continuations = wrap_title(labels[value], 30)
            lines.append(f"{count:>29,}{gnum(value):>10}  {label}".rstrip())
            lines.extend(" " * 41 + line for line in continuations)
        if missing:
            lines.append(f"{missing:>29,}{'.':>10}")
    else:
        _, mean, variance = moments(values)
        sorted_values = np.sort(values)
        percentiles = [gnum(pctile(sorted_values, p), 8) for p in (10, 25, 50, 75, 90)]
        lines.extend([
            f"{'Mean:':>23} {gnum(mean, 8):>7}",
            f"{'Std. dev.:':>23} {gnum(np.sqrt(variance), 8):>7}",
            "",
            "           Percentiles:     10%       25%       50%       75%       90%",
            f"{percentiles[0]:>31}" + "".join(f"{p:>10}" for p in percentiles[1:]),
        ])
    return lines
