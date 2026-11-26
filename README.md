# Open Stats Engine

A free engine that runs code written for Stata. Give it an unmodified do-file
and its data, and it aims to produce the results the do-file's author got. It
runs on a laptop, in CI and in a browser page, with nothing to buy or license.

Open Stats Engine is an independent project. It is not affiliated with,
endorsed by or sponsored by StataCorp LLC. Stata is a registered trademark of
StataCorp LLC; we use the name only to say which language the engine reads.

**Status: early.** Many commands are not built yet. Each one the engine lacks
stops the run with "not implemented".

Data comes in from `.dta` files and from comma-separated files through
`import delimited` and `insheet` ([what the reader does](docs/estimators/import-delimited.md)).
The reader splits on commas only: a file with a tab or semicolon outside quotes
stops with "not implemented" for now, and so does an integer that would lose digits.

## How we measure it

One number: the share of commands from published replication packages that
the engine runs with output matching the authors' own logs. The public figure
comes from a held-out set whose expected outputs the people building the
engine do not read. The matching rules are in `docs/matching-rules.md`; each
change to them carries a date and a reason.

Anything the engine does not support stops with "not implemented". It never
prints a guessed number.

## Run from source

Run these commands from the repository root (the folder holding this README)
with Python 3.11 or newer.
The virtual environment installs dependencies. `PYTHONPATH=engine` loads
the engine directly from the source tree for this command.

    python3 -m venv .venv && .venv/bin/pip install numpy scipy pytest
    PYTHONPATH=engine .venv/bin/python -m ose run /path/to/FILE.do --cwd /path/to/DIR

To run the unit tests or score the open cases, stay at the repository root.

    .venv/bin/python -m pytest -q tests/unit -p no:cacheprovider
    .venv/bin/python harness/run.py --set open

To score one case, which needs only that case's package, add its ID (the
file name under `tests/cases/open/` without `.json`):

    .venv/bin/python harness/run.py --set open --case dv-HNPXO1-15_figure_a1

The harness prints the aggregate score and writes it to `out/score.json`.
Open `out/results.json` for per-command results. Exit code `0` means the
harness completed, not that the case matched. For a one-case run,
`cases_fully_matched: 1` means the scorer credited the whole case.
`AMBIGUOUS` means the output matched, but the scorer could not read the
command's echo in one of the two logs, so it cannot confirm which command
produced that output; the command earns no credit. See the
[matching rules](docs/matching-rules.md).

Test cases are pointers, not files. The harness downloads each author's
package from its archive at test time, checks its SHA-256 and keeps it in
`$OSE_CACHE` (default `~/.cache/open-stats-engine`). The full open set
fetches every package on a first run, so it needs network and disk space.
Log matching uses the wording table shipped at `harness/wording-table.tsv`;
`score.json` names its hash under `wording_table`.

## Layout

- `engine/ose/` the engine (`lexer`, `macro`, `expr`, `syntax`, `interp`, `dta`, `fmt`, `commands/`)
- `harness/` case fetching, log matching (`logmatch.py`) and the runner (`run.py`)
- `tests/cases/open/` open cases: archive, DOI, licence, retrieval date and hashes
- `tests/unit/` unit tests
- `corpus/` scripts that find public replication packages, and `corpus/CENSUS.md`
- `docs/decisions.md` architecture, `docs/matching-rules.md` scoring rules,
  `docs/estimators/` the algorithm and source behind each estimator
- `web/` the browser workspace (the engine under Pyodide)

## How it was written

AI agents working for CyberNative AI LLC wrote nearly all of this code and its
documentation, under rules the company set and reviews. Copyright protection
for machine-written code may be limited. Whatever rights we hold, we license
under Apache-2.0.

## Clean-room rules

These bind everyone who contributes. `CONTRIBUTING.md` says how to sign off.

1. Never install, run, trial or remotely use Stata or any StataCorp program.
2. Never read or copy StataCorp files (`.ado`, `.mata`, `.sthlp`, `.dlg`,
   datasets) from any source.
3. Public documentation may be read to learn what a command does, and cited by
   URL. Never save manual or help text in the tree, on a working machine or in
   a prompt. Write code, docs, messages and tests in our own words. Names of
   commands, options and functions and the layout of numeric output are
   functional and may match.
4. Output layouts are learned from authors' published logs and pinned by tests.
5. Every test case records archive, DOI, licence, retrieval date and hashes.
   Authors' logs and data are never stored in the tree or shipped in a release.
6. A contribution whose origin cannot be traced does not merge.
7. Unsupported input fails with "not implemented". Never print a guessed number.

If you find a possible breach (a file of unknown origin, pasted manual text),
stop that piece and tell the maintainers what you found and where.

## Licence

Apache License 2.0, see `LICENSE` and `NOTICE`. Copyright 2026 CyberNative AI LLC.
Each replication package keeps its authors' licence, recorded in its case file.
