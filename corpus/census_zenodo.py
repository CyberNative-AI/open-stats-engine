#!/usr/bin/env python3
"""Census of Zenodo replication communities: do-files and logs inside package zips.

Anonymous API. Zip contents are listed with HTTP range requests (central
directory only); up to three .log members per record are read to tell
Stata logs from other logs. Resumable: per-record results cached under OUT.

Usage: census_zenodo.py OUT [--community restud-replication ...]
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

UA = "open-stats-engine-census/0.1 (research corpus census)"
STATA_LOG = re.compile(r"^\s*log type:\s*(text|smcl)", re.M)
CMD = re.compile(r"^\. \S", re.M)


def get(url, rng=None, tries=4, timeout=120):
    last = None
    for i in range(tries):
        try:
            h = {"User-Agent": UA}
            if rng:
                h["Range"] = f"bytes={rng[0]}-{rng[1]}"
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                data = r.read()
            time.sleep(0.3)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (401, 403, 404, 410):
                raise
            time.sleep(5 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


class RangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP ranges, with a small block cache."""

    def __init__(self, url, size, block=1 << 16):
        self.url, self.size, self.pos, self.block = url, size, 0, block
        self.cache = {}
        self.fetched = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        out = bytearray()
        while n > 0:
            b = self.pos // self.block
            if b not in self.cache:
                lo = b * self.block
                hi = min(lo + self.block, self.size) - 1
                self.cache[b] = get(self.url, (lo, hi))
                self.fetched += hi - lo + 1
                if self.fetched > 64 << 20:
                    raise RuntimeError("range budget exceeded")
            chunk = self.cache[b][self.pos - b * self.block:]
            take = chunk[:n]
            out += take
            self.pos += len(take)
            n -= len(take)
        return bytes(out)

    def readinto(self, buf):
        d = self.read(len(buf))
        buf[:len(d)] = d
        return len(d)


def classify(text):
    head = text[:20000]
    if head.lstrip().startswith("{smcl}"):
        return "smcl"
    if STATA_LOG.search(head) or len(CMD.findall(head)) >= 3:
        return "stata-text"
    return "other"


def records(community):
    page = 1
    while True:
        url = f"https://zenodo.org/api/records?communities={community}&size=25&page={page}&sort=oldest"
        d = json.loads(get(url))
        hits = d["hits"]["hits"]
        if not hits:
            return
        for r in hits:
            yield r
        page += 1


def census_record(r):
    out = {"id": r["id"], "title": r["metadata"].get("title", "")[:200],
           "licence": (r["metadata"].get("license") or {}).get("id", "none stated"),
           "access": (r["metadata"].get("access_right") or ""), "files": [], "members": {}, "logs": []}
    files = r.get("files") or []
    out["files"] = [f["key"] for f in files]
    ext = {}

    def bump(name):
        e = os.path.splitext(name.lower())[1]
        if e in (".do", ".log", ".smcl", ".dta", ".ado", ".r", ".py", ".m", ".csv", ".xlsx"):
            ext[e] = ext.get(e, 0) + 1

    for f in files:
        bump(f["key"])
    for f in files:
        if not f["key"].lower().endswith(".zip"):
            continue
        try:
            rf = RangeFile(f["links"]["self"], f["size"])
            z = zipfile.ZipFile(io.BufferedReader(rf, 1 << 16))
            names = z.namelist()
            for n in names:
                if "__MACOSX" in n:
                    continue
                bump(n)
            logs = [n for n in names if n.lower().endswith(".log") and "__MACOSX" not in n]
            for n in logs[:3]:
                info = z.getinfo(n)
                if info.file_size > 2_000_000:
                    out["logs"].append({"name": n, "kind": "too-large"})
                    continue
                text = z.read(n).decode("utf-8", "replace")
                out["logs"].append({"name": n, "kind": classify(text), "commands": len(CMD.findall(text))})
        except Exception as e:
            out.setdefault("errors", []).append(f"{f['key']}: {repr(e)[:200]}")
    out["members"] = ext
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--community", action="append", default=None)
    a = ap.parse_args()
    comms = a.community or ["restud-replication"]
    os.makedirs(a.out, exist_ok=True)
    for c in comms:
        d = os.path.join(a.out, c)
        os.makedirs(d, exist_ok=True)
        for n, r in enumerate(records(c)):
            p = os.path.join(d, f"{r['id']}.json")
            if os.path.exists(p):
                continue
            json.dump(census_record(r), open(p, "w"))
            if n % 20 == 0:
                print(f"{c}: {n}", flush=True)
    rows = []
    for c in comms:
        d = os.path.join(a.out, c)
        for fn in sorted(os.listdir(d)):
            rec = json.load(open(os.path.join(d, fn)))
            m = rec["members"]
            kinds = [x.get("kind") for x in rec["logs"]]
            rows.append({"community": c, "id": rec["id"], "licence": rec["licence"], "has_files": bool(rec["files"]),
                         "do": m.get(".do", 0), "log": m.get(".log", 0), "smcl": m.get(".smcl", 0),
                         "dta": m.get(".dta", 0), "stata_log_seen": any(k in ("stata-text", "smcl") for k in kinds)
                         or m.get(".smcl", 0) > 0, "errors": bool(rec.get("errors"))})
    summ = {"records": len(rows), "with_files": sum(r["has_files"] for r in rows),
            "with_do": sum(1 for r in rows if r["do"]),
            "with_do_and_log": sum(1 for r in rows if r["do"] and (r["log"] or r["smcl"])),
            "with_do_and_stata_log": sum(1 for r in rows if r["do"] and r["stata_log_seen"]),
            "with_do_stata_log_and_dta": sum(1 for r in rows if r["do"] and r["stata_log_seen"] and r["dta"]),
            "by_licence": {}}
    for r in rows:
        if r["do"] and r["stata_log_seen"]:
            summ["by_licence"][r["licence"]] = summ["by_licence"].get(r["licence"], 0) + 1
    json.dump({"summary": summ, "rows": rows}, open(os.path.join(a.out, "census.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    sys.exit(main())
