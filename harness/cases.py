"""Case files, fetching and workspace layout.

A case is a JSON file under tests/cases/<set>/<id>.json:

  {"id": ..., "set": "open" | "heldout",
   "source": {"archive": "Harvard Dataverse", "doi": ..., "version": ..., "licence": ...,
              "licence_note": ..., "retrieved": "YYYY-MM-DD"},
   "files": [{"path": "data/analytical/final.dta", "file_id": 14443919, "original": true,
              "sha256": ...}, ...],
   "dofile": "02_analysis/15_figure_a1_distance_distribution.do",
   "cwd": ".",
   "expected_log": {"file_id": ..., "sha256": ...},
   "produced_log": "output/logs/02_analysis/15_figure_a1_distance_distribution.log"}

Files are fetched at test time into the cache (bulk storage), checked
against the recorded sha256, and linked into a fresh workspace.
"""
import hashlib
import json
import os
import shutil
import urllib.request

CACHE = os.environ.get("OSE_CACHE", os.path.expanduser("~/.cache/open-stats-engine"))
UA = "open-stats-engine-harness/0.1"
DV = "https://dataverse.harvard.edu/api/access/datafile/"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(entry, archive="dataverse"):
    fid = entry["file_id"]
    orig = entry.get("original", False)
    d = os.path.join(CACHE, archive)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{fid}{'.orig' if orig else ''}")
    if not os.path.exists(p):
        url = DV + str(fid) + ("?format=original" if orig else "")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=600) as r, open(p + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(p + ".part", p)
    want = entry.get("sha256")
    if want and sha256(p) != want:
        raise RuntimeError(f"sha256 mismatch for file {fid}")
    return p


def load(path):
    with open(path) as f:
        return json.load(f)


def workspace(case, root):
    """Create a fresh workspace with the case's files at their paths."""
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root)
    for d in case.get("dirs", []):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    for e in case["files"]:
        src = fetch(e)
        dst = os.path.join(root, e["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy(src, dst)
        os.chmod(dst, 0o444) if not e["path"].endswith(".do") else None
    return root


def expected_text(case):
    p = fetch(case["expected_log"])
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()
