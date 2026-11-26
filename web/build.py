"""Prepare the loopback-only workspace and its pinned browser runtime."""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
BUILD = WEB / ".build"
REPLICATION_DATA = WEB / ".replication" / "final.dta"
RUNTIME = "https://cdn.jsdelivr.net/pyodide/v0.29.4/full/"
DATAVERSE = "https://dataverse.harvard.edu/api/access/datafile/"
CASE = ROOT / "tests/cases/open/dv-HNPXO1-15_figure_a1.json"
RUNTIME_ASSETS = {
    "pyodide.js": "7be9e63eddf6bd8786a5ab71c8689c35731d187e3415fe58d7cb95423b50421a",
    "pyodide.asm.js": "fe75e97ef2c7a10c41f23b96344c553c7c1c62821bb206080dbb24941c06d5f3",
    "pyodide.asm.wasm": "10090fe41e019ae669d512e1f747021a8db2aaab0f6dd6f85fa9368c55d681e3",
    "python_stdlib.zip": "92cb24faa546818f3ef4050fd5bd2b6487bd2042efed2113af141d035f30efb4",
    "pyodide-lock.json": "14d2c2dba101277999e17135e653d8f15389ad1437f53eae213bf0c3cdff723d",
}


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def stage(url, dest, sha256, *, local=None):
    if dest.is_file() and digest(dest) == sha256:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=dest.parent, delete=False) as file:
        temp = Path(file.name)
        try:
            if local and local.is_file() and digest(local) == sha256:
                with local.open("rb") as source:
                    shutil.copyfileobj(source, file)
            else:
                request = Request(url, headers={"User-Agent": "open-stats-engine-browser-spike/0.1"})
                with urlopen(request, timeout=45) as source:
                    shutil.copyfileobj(source, file)
            file.flush()
            if digest(temp) != sha256:
                raise ValueError(f"SHA-256 mismatch for {dest.name}")
            temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)


def stage_histogram_preview():
    """Render the standalone companion with same-origin CSS and fonts."""
    source = (WEB / "x-histogram.html").read_text(encoding="utf-8")
    head, remainder = source.split("<style>", 1)
    style, body = remainder.split("</style>", 1)

    faces = {digest(path): path.name for path in (WEB / "atlas").glob("*.woff2")}

    def hosted_font(match):
        font_hash = hashlib.sha256(base64.b64decode(match[1], validate=True)).hexdigest()
        if font_hash not in faces:
            raise ValueError("The histogram companion embeds a font missing from web/atlas")
        return f'url("atlas/{faces[font_hash]}")'

    style = re.sub(r'url\("data:font/woff2;base64,([^"]+)"\)', hosted_font, style)
    (BUILD / "x-histogram-preview.css").write_text(style, encoding="utf-8")
    link = '<link rel="stylesheet" href="x-histogram-preview.css">'
    (BUILD / "x-histogram-preview.html").write_text(head + link + body, encoding="utf-8")


def build(cache, research_examples):
    runtime = BUILD / "pyodide"
    lock = runtime / "pyodide-lock.json"
    stage(RUNTIME + lock.name, lock, RUNTIME_ASSETS[lock.name])
    packages = json.loads(lock.read_text())["packages"]
    runtime_assets = dict(RUNTIME_ASSETS)
    for name in ("numpy", "scipy"):
        item = packages[name]
        runtime_assets[item["file_name"]] = item["sha256"]

    case = json.loads(CASE.read_text())
    data, figure = case["files"]
    samples = BUILD / "examples"
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [
            pool.submit(stage, RUNTIME + name, runtime / name, sha256)
            for name, sha256 in runtime_assets.items()
        ]
        jobs += [
            pool.submit(stage, DATAVERSE + str(figure["file_id"]), samples / "figure-a1.do",
                        figure["sha256"], local=cache / str(figure["file_id"])),
            pool.submit(stage, DATAVERSE + "14443936", samples / "table-2.do",
                        "7212c894695c03b47695feb75bb9be673861df4eba98c3ed393168516d715ce7"),
            pool.submit(stage, DATAVERSE + "14443860", samples / "HNPXO1-LICENSE.txt",
                        "046b5fe473e9861b8ebb8ba49c582a298484a5a76be421ba3e7234d61ea0780a"),
        ]
        if research_examples:
            file_id = str(data["file_id"])
            jobs.append(pool.submit(
                stage, DATAVERSE + file_id + "?format=original", REPLICATION_DATA,
                data["sha256"], local=cache / f"{file_id}.orig",
            ))
        for job in jobs:
            job.result()
    (samples / "workspace.json").write_text(
        json.dumps({"path": data["path"], "dirs": case["dirs"]}), encoding="utf-8",
    )

    stage_workspace()


def stage_workspace():
    for name in ("index.html", "workspace.css", "workspace.js", "worker.js", "x-histogram.html"):
        shutil.copyfile(WEB / name, BUILD / name)
    shutil.copytree(WEB / "atlas", BUILD / "atlas", dirs_exist_ok=True)
    stage_histogram_preview()
    with ZipFile(BUILD / "ose.zip", "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "engine/ose").rglob("*.py")):
            archive.write(path, path.relative_to(ROOT / "engine"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-replication-data", action="store_true",
                        help="prepare final.dta for personal replication on loopback")
    parser.add_argument("--dataverse-cache", type=Path,
                        default=Path(os.environ.get("OSE_CACHE", Path.home() / ".cache" / "open-stats-engine")) / "dataverse")
    args = parser.parse_args()
    build(args.dataverse_cache, args.with_replication_data)
    print(f"Prepared {BUILD}")
