#!/usr/bin/env python3
"""Make open-set case files for one Dataverse package.

Pairs every do-file in --dodir with the log of the same base name (anywhere in the package), adds the
--data files (package paths, fetched in their original format), fetches everything through the harness
cache, pins sha256, and writes tests/cases/open/<id>.json. Skips a do-file with no log, or a log that more
than one do-file could own. Only for packages on corpus/open-list.tsv: refuses others, so a held-out
package cannot be opened by accident.

  make_cases.py --doi doi:10.7910/DVN/HNPXO1 --dodir 02_analysis --data data/analytical/final.dta \
      --licence "Split terms, LICENSE.txt of the package (see the case manifests for per-file terms)" [--skip 15_figure_a1_distance_distribution]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "harness"))
import cases as C  # noqa: E402

API = "https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId="


def open_list():
    ids = set()
    with open(os.path.join(HERE, "open-list.tsv")) as f:
        for ln in f:
            if ln.strip() and not ln.startswith("#"):
                ids.add(ln.split("\t")[1].strip())
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doi", required=True)
    ap.add_argument("--dodir", required=True)
    ap.add_argument("--data", action="append", default=[])
    ap.add_argument("--licence", required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--skip", action="append", default=[])
    a = ap.parse_args()
    if a.doi not in open_list():
        sys.exit(f"{a.doi} is not on corpus/open-list.tsv; add it there first (and only if a builder may read it)")
    req = urllib.request.Request(API + a.doi, headers={"User-Agent": C.UA})
    ver = json.load(urllib.request.urlopen(req, timeout=120))["data"]["latestVersion"]
    files = []
    for f in ver["files"]:
        df = f["dataFile"]
        path = (f.get("directoryLabel", "") + "/" if f.get("directoryLabel") else "") + df["filename"]
        if df.get("originalFileFormat") and path.endswith(".tab"):
            path = path[:-4] + ".dta"  # ingested Stata file: the original is the .dta the do-files read
        files.append({"path": path, "id": df["id"], "orig": bool(df.get("originalFileFormat")),
                      "restricted": f.get("restricted", False)})
    by_path = {x["path"]: x for x in files}
    logs = {}
    for x in files:
        if x["path"].endswith(".log"):
            logs.setdefault(os.path.basename(x["path"])[:-4], []).append(x)
    short = a.doi.rsplit("/", 1)[-1]
    data = []
    for p in a.data:
        x = by_path[p]
        if x["restricted"]:
            sys.exit(f"{p} is restricted")
        e = {"path": p, "file_id": x["id"], "original": x["orig"]}
        e["sha256"] = C.sha256(C.fetch(e))
        data.append(e)
    out_dir = os.path.join(ROOT, "tests", "cases", "open")
    made = []
    for x in sorted(files, key=lambda x: x["path"]):
        root = a.dodir.strip("/") in ("", ".")  # --dodir . : do-files at the package root
        in_dir = "/" not in x["path"] if root else x["path"].startswith(a.dodir.rstrip("/") + "/")
        if not (in_dir and x["path"].endswith(".do")):
            continue
        stem = os.path.basename(x["path"])[:-3]
        if stem in a.skip or stem == "main":
            continue
        cand = logs.get(stem, [])
        if len(cand) != 1:
            print(f"skip {stem}: {len(cand)} logs of that name", file=sys.stderr)
            continue
        lg = cand[0]
        do = {"path": x["path"], "file_id": x["id"], "original": False}
        do["sha256"] = C.sha256(C.fetch(do))
        exp = {"file_id": lg["id"]}
        exp["sha256"] = C.sha256(C.fetch(exp))
        text = open(C.fetch(do), encoding="utf-8", errors="replace").read()
        dirs = sorted({os.path.dirname(m.strip('"'))
                       for m in re.findall(r'(?:log using|graph export|save|export \w+ using|esttab using|'
                                           r'outreg2 using|putdocx save)\s+("[^"]+"|\S+)', text)
                       if os.path.dirname(m.strip('"')) and "$" not in m and "`" not in m})
        case = {
            "id": f"dv-{short}-{stem}", "set": "open",
            "source": {"archive": "Harvard Dataverse", "doi": a.doi,
                       "version": f'{ver.get("versionNumber")}.{ver.get("versionMinorNumber")}',
                       "url": "https://doi.org/" + a.doi[4:], "licence": a.licence, "licence_note": a.note,
                       "retrieved": time.strftime("%Y-%m-%d")},
            "files": data + [do], "dofile": x["path"], "cwd": ".",
            "expected_log": exp, "dirs": dirs,
        }
        p = os.path.join(out_dir, case["id"] + ".json")
        with open(p, "w") as f:
            json.dump(case, f, indent=1, ensure_ascii=False)
            f.write("\n")
        made.append(case["id"])
    print("\n".join(made))


if __name__ == "__main__":
    main()
