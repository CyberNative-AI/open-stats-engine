#!/usr/bin/env python3
"""Census of Harvard Dataverse replication packages that hold Stata do-files and logs.

Anonymous public API only. Resumable: every API answer is cached under OUT.

  phase search   : page the file search for .do, .log and .smcl files, group by dataset
  phase datasets : for datasets holding a do-file and a log, fetch metadata (licence, file list)
  phase logs     : download each public log under the size cap, classify it as a Stata log or not
  phase report   : write census.json and census.md

Usage: census_dataverse.py OUT [--phases search,datasets,logs,report] [--max-log-bytes N]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://dataverse.harvard.edu"
UA = "open-stats-engine-census/0.1 (research corpus census)"
QUERIES = {
    "do": {"q": "*", "fq": "fileContentType:text/x-stata-syntax"},
    "do_name": {"q": "fileName:*.do"},
    "log": {"q": "fileName:*.log"},
    "smcl": {"q": "fileName:*.smcl"},
}


class Blocked(Exception):
    """The archive refused us as a client (403/429), not this one record. Never recorded per dataset."""


PACE = 1.0          # seconds between requests: Harvard Dataverse blocked us at ~4/s on 2026-11-24
BLOCK_WAITS = [300, 600, 1200, 2400, 3600, 3600, 3600]  # ~4 h of probes, one request each, then give up


def get(url, binary=False, tries=4, timeout=120):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            time.sleep(PACE)
            return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} on {url}")
            if e.code in (401, 404):
                raise
            time.sleep(5 * (i + 1))
        except Exception as e:  # network trouble: back off and retry
            last = e
            time.sleep(5 * (i + 1))
    raise last


def get_patient(url, binary=False):
    """get(), waiting out a client block instead of failing the record. Exits 75 if the block outlasts ~4 h."""
    for w in BLOCK_WAITS + [None]:
        try:
            return get(url, binary=binary)
        except Blocked as e:
            if w is None:
                print(f"blocked for good: {e}", flush=True)
                sys.exit(75)
            print(f"blocked ({e}); waiting {w}s", flush=True)
            time.sleep(w)


def phase_search(out):
    path = os.path.join(out, "search.json")
    state = json.load(open(path)) if os.path.exists(path) else {}
    for key, params in QUERIES.items():
        st = state.setdefault(key, {"start": 0, "total": None, "items": []})
        while st["total"] is None or st["start"] < st["total"]:
            qs = dict(params, type="file", per_page=1000, start=st["start"])
            url = BASE + "/api/search?" + urllib.parse.urlencode(qs)
            d = get_patient(url)["data"]
            st["total"] = d["total_count"]
            for it in d["items"]:
                st["items"].append({k: it.get(k) for k in (
                    "name", "file_id", "dataset_persistent_id", "size_in_bytes",
                    "file_content_type", "restricted", "md5")})
            st["start"] += 1000
            if not d["items"]:
                break
            json.dump(state, open(path + ".tmp", "w"))
            os.replace(path + ".tmp", path)
            print(f"search {key}: {st['start']}/{st['total']}", flush=True)
    json.dump(state, open(path, "w"))
    return state


def grouped(state):
    ds = {}
    for key, st in state.items():
        kind = "do" if key.startswith("do") else key
        for it in st["items"]:
            name = (it["name"] or "").lower()
            if kind == "do" and not name.endswith(".do"):
                continue
            if kind == "log" and not name.endswith(".log"):
                continue
            if kind == "smcl" and not name.endswith(".smcl"):
                continue
            pid = it["dataset_persistent_id"]
            if not pid:
                continue
            ds.setdefault(pid, {"do": {}, "log": {}, "smcl": {}})[kind][it["file_id"]] = it
    return ds


def candidates(out):
    state = json.load(open(os.path.join(out, "search.json")))
    ds = grouped(state)
    return ds, sorted(p for p, v in ds.items() if v["do"] and (v["log"] or v["smcl"]))


def safe(pid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", pid)


def phase_datasets(out):
    _, cands = candidates(out)
    d = os.path.join(out, "datasets")
    os.makedirs(d, exist_ok=True)
    for n, pid in enumerate(cands):
        f = os.path.join(d, safe(pid) + ".json")
        if os.path.exists(f):
            continue
        url = BASE + "/api/datasets/:persistentId/?" + urllib.parse.urlencode({"persistentId": pid})
        try:
            meta = get_patient(url)
        except Exception as e:  # 401/404 or repeated network failure: a fact about this record
            meta = {"error": repr(e)}
        json.dump(meta, open(f, "w"))
        if n % 50 == 0:
            print(f"datasets {n}/{len(cands)}", flush=True)


def licence_of(meta):
    v = (meta.get("data") or {}).get("latestVersion") or {}
    lic = v.get("license")
    if isinstance(lic, dict):
        return lic.get("name") or "unknown"
    if isinstance(lic, str):
        return lic
    if v.get("termsOfUse"):
        return "custom terms"
    return "none stated"


def files_of(meta):
    v = (meta.get("data") or {}).get("latestVersion") or {}
    return v.get("files") or []


STATA_LOG = re.compile(r"^\s*log type:\s*(text|smcl)", re.M)
CMD = re.compile(r"^\. \S", re.M)


def classify(text):
    head = text[:20000]
    if head.lstrip().startswith("{smcl}"):
        return "smcl"
    if STATA_LOG.search(head) or len(CMD.findall(head)) >= 3:
        return "stata-text"
    return "other"


def phase_logs(out, max_bytes):
    _, cands = candidates(out)
    d = os.path.join(out, "logs")
    os.makedirs(d, exist_ok=True)
    idx_path = os.path.join(out, "logs.json")
    idx = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    for n, pid in enumerate(cands):
        meta = json.load(open(os.path.join(out, "datasets", safe(pid) + ".json")))
        for fm in files_of(meta):
            df = fm.get("dataFile") or {}
            name = (df.get("filename") or fm.get("label") or "").lower()
            if not (name.endswith(".log") or name.endswith(".smcl")):
                continue
            fid = str(df.get("id"))
            if fid in idx:
                continue
            rec = {"pid": pid, "name": df.get("filename"), "size": df.get("filesize"),
                   "restricted": bool(fm.get("restricted"))}
            if rec["restricted"]:
                rec["status"] = "restricted"
            elif (df.get("filesize") or 0) > max_bytes:
                rec["status"] = "too-large"
            else:
                try:
                    raw = get_patient(f"{BASE}/api/access/datafile/{fid}", binary=True)
                    p = os.path.join(d, fid + os.path.splitext(name)[1])
                    open(p, "wb").write(raw)
                    text = raw.decode("utf-8", "replace")
                    rec.update(status="ok", sha256=hashlib.sha256(raw).hexdigest(),
                               kind=classify(text), commands=len(CMD.findall(text)))
                except urllib.error.HTTPError as e:
                    rec["status"] = f"http-{e.code}"
                except Exception as e:
                    rec["status"] = "error: " + repr(e)[:200]
            idx[fid] = rec
        if n % 25 == 0:
            json.dump(idx, open(idx_path + ".tmp", "w"))
            os.replace(idx_path + ".tmp", idx_path)
            print(f"logs {n}/{len(cands)} files={len(idx)}", flush=True)
    json.dump(idx, open(idx_path, "w"))


DATA_EXT = (".dta", ".csv", ".xlsx", ".xls", ".txt", ".sav", ".tab", ".dat", ".zip")


def phase_report(out):
    ds, cands = candidates(out)
    logs = json.load(open(os.path.join(out, "logs.json"))) if os.path.exists(os.path.join(out, "logs.json")) else {}
    by_pid = {}
    for fid, r in logs.items():
        by_pid.setdefault(r["pid"], []).append(r)
    rows = []
    for pid in cands:
        meta = json.load(open(os.path.join(out, "datasets", safe(pid) + ".json")))
        files = files_of(meta)
        names = [((f.get("dataFile") or {}).get("filename") or "") for f in files]
        orig = [((f.get("dataFile") or {}).get("originalFileFormat") or "") for f in files]
        restricted = sum(1 for f in files if f.get("restricted"))
        has_dta = any(n.lower().endswith(".dta") or "stata" in o.lower() for n, o in zip(names, orig))
        has_data = has_dta or any(n.lower().endswith(DATA_EXT) for n in names)
        lr = by_pid.get(pid, [])
        stata_logs = [r for r in lr if r.get("kind") in ("stata-text", "smcl")]
        rows.append({
            "pid": pid, "licence": licence_of(meta), "files": len(files), "restricted_files": restricted,
            "do_files": sum(1 for n in names if n.lower().endswith(".do")),
            "logs": len(lr), "stata_logs": len(stata_logs),
            "logged_commands": sum(r.get("commands", 0) for r in stata_logs),
            "has_dta": has_dta, "has_data": has_data,
            "meta_error": meta.get("error"),
        })
    open_lic = re.compile(r"^(CC0|CC BY(?! ?-?NC| ?-?ND)|CC-BY(?!-NC|-ND)|MIT|ODC|Apache|BSD)", re.I)
    def tier(r):
        if r["meta_error"]:
            return "metadata-error"
        if not r["stata_logs"]:
            return "no-stata-log"
        if not r["has_data"]:
            return "log-no-data"
        if r["restricted_files"]:
            return "usable-partly-restricted"
        return "usable"
    for r in rows:
        r["tier"] = tier(r)
        r["redistributable"] = bool(open_lic.match(r["licence"] or ""))
    summary = {
        "source": "Harvard Dataverse public search API, anonymous",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "datasets_with_do": sum(1 for v in ds.values() if v["do"]),
        "datasets_with_log_or_smcl": sum(1 for v in ds.values() if v["log"] or v["smcl"]),
        "datasets_with_both": len(cands),
        "by_tier": {}, "usable_by_licence": {}, "usable_logged_commands": 0,
    }
    for r in rows:
        summary["by_tier"][r["tier"]] = summary["by_tier"].get(r["tier"], 0) + 1
        if r["tier"] == "usable":
            summary["usable_by_licence"][r["licence"]] = summary["usable_by_licence"].get(r["licence"], 0) + 1
            summary["usable_logged_commands"] += r["logged_commands"]
    json.dump({"summary": summary, "rows": rows}, open(os.path.join(out, "census.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--phases", default="search,datasets,logs,report")
    ap.add_argument("--max-log-bytes", type=int, default=5_000_000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for ph in a.phases.split(","):
        print("== phase", ph, flush=True)
        if ph == "search":
            phase_search(a.out)
        elif ph == "datasets":
            phase_datasets(a.out)
        elif ph == "logs":
            phase_logs(a.out, a.max_log_bytes)
        elif ph == "report":
            phase_report(a.out)


if __name__ == "__main__":
    sys.exit(main())
