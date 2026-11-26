#!/usr/bin/env python3
"""Rank commands by how many real logs use them, from the census log cache.

Reads Stata text logs (kind 'stata-text' in logs.json), parses command blocks
with the harness parser, and counts for each command word: total uses and the
number of distinct logs (do-files) that use it. Also reports, per command,
how many logs would run past it if every command the engine already knows
were correct ("first unknown command" ranking).

Usage: command_freq.py CENSUS_DIR [--known engine]  -> prints JSON
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "harness"))
sys.path.insert(0, os.path.join(HERE, "..", "engine"))
import logmatch as L  # noqa: E402

PREFIX = {"capture", "cap", "capt", "quietly", "qui", "quietl", "noisily", "noi", "xi:", "by", "bysort", "bys"}


def cmd_word(key):
    k = key
    for _ in range(4):
        m = re.match(r"^(\w+)\s*(.*)$", k)
        if not m:
            return None
        w, rest = m.group(1), m.group(2)
        if w in ("by", "bysort", "bys"):
            j = rest.find(":")
            if j < 0:
                return w
            k = rest[j + 1:].strip()
            continue
        if w in PREFIX:
            k = rest.lstrip(":").strip()
            continue
        return w
    return None


def known_words():
    from ose import commands  # noqa: F401
    from ose.interp import REGISTRY, PREFIXES
    return REGISTRY, PREFIXES


def canon(word, reg):
    if word in reg:
        return word
    hits = [k for k, v in reg.items() if k.startswith(word) and len(word) >= v[0]]
    return hits[0] if len(hits) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("census_dir")
    a = ap.parse_args()
    idx = json.load(open(os.path.join(a.census_dir, "logs.json")))
    reg, _ = known_words()
    uses, logs_with, first_unknown = {}, {}, {}
    n_logs = 0
    n_cmds = 0
    for fid, r in idx.items():
        if r.get("kind") != "stata-text" or r.get("status") != "ok":
            continue
        p = os.path.join(a.census_dir, "logs", fid + ".log")
        if not os.path.exists(p):
            continue
        blocks = L.parse_log(open(p, encoding="utf-8", errors="replace").read())
        n_logs += 1
        seen = set()
        fu = None
        for b in blocks:
            if b.is_comment or b.is_logcmd:
                continue
            w = cmd_word(b.key)
            if not w:
                continue
            n_cmds += 1
            c = canon(w, reg) or w
            uses[c] = uses.get(c, 0) + 1
            seen.add(c)
            if fu is None and canon(w, reg) is None and w not in ("if", "else", "foreach", "forvalues", "while", "end", "program"):
                fu = w
        for c in seen:
            logs_with[c] = logs_with.get(c, 0) + 1
        if fu:
            first_unknown[fu] = first_unknown.get(fu, 0) + 1
    # Leak floor (same as the held-out feedback rule): a command name is shown only if at least 3 logs use it,
    # so the ranking never singles out one package. Reading command words this way does not put a package
    # on the open list; reading its outputs or per-package rows does (docs/matching-rules.md).
    top = sorted(((c, n) for c, n in logs_with.items() if n >= 3), key=lambda kv: -kv[1])[:80]
    first_unknown = {c: n for c, n in first_unknown.items() if n >= 3}
    out = {"logs": n_logs, "commands": n_cmds,
           "by_logs": [{"cmd": c, "logs": n, "uses": uses[c], "known": c in reg} for c, n in top],
           "first_unknown_blocks_logs": sorted(first_unknown.items(), key=lambda kv: -kv[1])[:40]}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
