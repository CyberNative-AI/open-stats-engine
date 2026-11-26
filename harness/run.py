#!/usr/bin/env python3
"""Run cases and write a score.

  run.py [--set open] [--case ID] [--out DIR]

Deterministic, no model. Writes DIR/score.json and DIR/results.json.
"""
import argparse
import glob
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cases as C  # noqa: E402
import logmatch as L  # noqa: E402

PY = os.environ.get("OSE_PYTHON", sys.executable)


def log_linesize(text):
    """The author's line width, read off the rule above the log header ("log:" / "name:"): width + 1.

    HNPXO1 shows a 79-wide rule with the documented default of 80. No header: None (the engine uses 80).
    The held-out scorer derives the width the same way, independently.
    """
    lines = text.splitlines()
    for i, l in enumerate(lines[:-1]):
        if len(l) >= 40 and set(l) == {"-"} and re.match(r"^\s*(log|name):", lines[i + 1]):
            return len(l) + 1
    return None


def run_case(case, work, timeout=600):
    ws = C.workspace(case, os.path.join(work, case["id"]))
    cwd = os.path.join(ws, case.get("cwd", "."))
    # Rules section 3 (.14.7): the transcript scored is this invocation's own. The engine writes into a directory made for
    # this run alone, and any transcript a previous run left at the kept path is removed before the engine starts,
    # so a run that ends before it opens its transcript is scored with none, never with an earlier run's bytes.
    transcript = os.path.join(work, case["id"] + ".transcript.log")
    if os.path.lexists(transcript):
        os.unlink(transcript)
    own_dir = tempfile.mkdtemp(prefix=case["id"] + ".run-", dir=work)
    own = os.path.join(own_dir, "transcript.log")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "engine"))
    ls = log_linesize(C.expected_text(case))
    extra = ["--linesize", str(ls)] if ls else []
    t0 = time.time()
    code, timed_out = None, False
    try:
        p = subprocess.run([PY, "-s", "-m", "ose", "run", os.path.join(ws, case["dofile"]), "--cwd", cwd,
                            "--transcript", own] + extra, env=env, capture_output=True, text=True, timeout=timeout,
                           cwd=os.path.join(ROOT, "engine"))
        code = p.returncode
        status = {0: "ok", 1: "error", 2: "unsupported", 3: "crash"}.get(code, "crash")
        stderr = p.stderr[-2000:]
    except subprocess.TimeoutExpired:
        # No process status exists: the scorer is told the run timed out, never handed a stand-in exit code
        # (rules section 3, .14.6).
        status, stderr, timed_out = "timeout", "", True
    secs = time.time() - t0
    # io-contract: the scored record is the engine's transcript, the same file the held-out scorer reads.
    actual = None
    if os.path.exists(own):
        with open(own, "rb") as f:
            actual = f.read().decode("utf-8", "replace")
        os.replace(own, transcript)  # kept beside the workspace, for rescoring and evidence
    shutil.rmtree(own_dir, ignore_errors=True)
    res = L.match_logs(C.expected_text(case), actual, exit_code=code, timed_out=timed_out)
    return {"id": case["id"], "package": case["source"]["doi"], "status": status, "exit": code,
            "seconds": round(secs, 2), "stderr": stderr, "summary": L.summarize(res), "commands": res}


def bootstrap(results, reps=2000, seed=20261124):
    """Package-level bootstrap interval (95%) on the pooled headline score."""
    import random
    pk = {}
    for r in results:
        a = pk.setdefault(r["package"], [0, 0])
        a[0] += r["summary"]["matched"]
        a[1] += r["summary"]["commands"]
    vals = list(pk.values())
    if len(vals) < 2:
        return None
    rng = random.Random(seed)
    est = []
    for _ in range(reps):
        smp = [vals[rng.randrange(len(vals))] for _ in vals]
        d = sum(v[1] for v in smp)
        if d:
            est.append(sum(v[0] for v in smp) / d)
    est.sort()
    return [round(est[int(0.025 * len(est))], 4), round(est[int(0.975 * len(est)) - 1], 4)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="open")
    ap.add_argument("--case", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(ROOT, "tests", "cases", a.set, "*.json")))
    cs = [C.load(f) for f in files]
    if a.case:
        cs = [c for c in cs if c["id"] == a.case]
    os.makedirs(a.out, exist_ok=True)
    work = os.path.join(a.out, "work")
    results = [run_case(c, work) for c in cs]
    keys = list(results[0]["summary"]) if results else []
    tot = {k: sum(r["summary"][k] for r in results) for k in keys}
    full = sum(1 for r in results if r["summary"]["commands"] and r["summary"]["matched"] == r["summary"]["commands"])
    blockers = {}
    for r in results:
        first = next((c for c in r["commands"] if not c["excluded"] and c["cls"] != "MATCH"), None)
        if first:
            w = L._cmd_body(first["cmd"]).split()[0] if first["cmd"] else "?"
            blockers.setdefault(f'{first["cls"]}:{w}', []).append(r["id"])
    pk = {}
    for r in results:
        acc = pk.setdefault(r["package"], [0, 0])
        acc[0] += r["summary"]["matched"]
        acc[1] += r["summary"]["commands"]

    def ratio(n, d):
        return round(n / d, 4) if d else None
    score = {
        "date": time.strftime("%Y-%m-%d"), "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "set": a.set, "rules": L.MATCH_RULES_VERSION, "wording_table": L.WORDING_HASH[:12], "cases": len(results), "packages": len(pk),
        "cases_fully_matched": full, **tot,
        "score": ratio(tot.get("matched", 0), tot.get("commands", 0)),
        "score_interval_95": bootstrap(results),
        "score_package_mean": ratio(sum(v[0] / v[1] for v in pk.values() if v[1]), sum(1 for v in pk.values() if v[1])),
        "score_unwitnessed": ratio(tot.get("matched_unwitnessed", 0), tot.get("commands", 0)),
        "score_strict": ratio(tot.get("matched_strict", 0), tot.get("commands", 0)),
        "score_with_output": ratio(tot.get("with_output_matched", 0), tot.get("with_output", 0)),
        "first_failure_by_command": {k: len(v) for k, v in sorted(blockers.items(), key=lambda kv: -len(kv[1]))},
    }
    json.dump(results, open(os.path.join(a.out, "results.json"), "w"), indent=1)
    json.dump(score, open(os.path.join(a.out, "score.json"), "w"), indent=1)
    print(json.dumps(score, indent=1))


if __name__ == "__main__":
    main()
