# Corpus census

Question: how many public replication packages contain both do-files and the
authors' own logs, by archive and licence, and how many can be test cases
under the provenance rule (source, licence, retrieval date and hash recorded;
pointer-and-fetch where redistribution is unclear)?

Status: **coarse pass complete for anonymous Dataverse and Zenodo ReStud, 2026-11-25 02:58 UTC.
The eligibility pass has not run.**

## Answer so far (2026-11-25)

1,129 Dataverse datasets and 71 Zenodo ReStud records pass the coarse test below. That
is a count of candidates, not of test cases. The coarse test does not check that a log
came from a do-file in the package, that every input it reads is present, or that it ran
without an unhandled error. A stricter eligibility pass checks those; until it has run,
we do not know how many packages qualify, and the size of the held-out pool stays open.

| Archive (anonymous) | Do-file + log | Stata log | + data, unrestricted ("usable", coarse) | Licence of usable |
|---|---|---|---|---|
| Harvard Dataverse | 1,287 | 1,157 (of 1,243 with readable metadata) | **1,129** (+5 partly restricted; 23 log without data; 44 metadata errors) | CC0 1.0: 1,053 · custom terms: 67 · CC BY 4.0: 7 · CC BY-NC-ND 4.0: 2 |
| Zenodo `restud-replication` | 103 | 79 | **71** (with `.dta`) | CC-BY-4.0: 76 of 79 · other: 3 |

"Usable, coarse" is the dataset-level test in `corpus/census_dataverse.py` (`tier()`): at
least one Stata text or SMCL log, at least one data file, no restricted file. It does
not check that the log belongs to a do-file in the package, that every file the log reads
is present, or per-file terms. The dataset licence is not the last word: HNPXO1 is CC0 at
the archive, yet its `LICENSE.txt` forbids redistributing `final.dta`. So every case stays
pointer-and-fetch, and the per-file licence is recorded when a case is built.

Logged commands in usable Dataverse logs: 489,110. Downloaded logs in the same run
(2026-11-25 02:58 UTC): 3,332 files, 604,477,748 bytes, of 3,439 attempted (58 refused
by the server with HTTP 400, 32 over the size limit, 17 restricted). They are kept
outside the tree and never committed.

### Corpus-wide command ranking (engine command set of 2026-11-25 03:25 UTC, `corpus/command_freq.py`)

1,771 Stata text logs, 360,668 commands. The first command the engine does not know,
counted in logs it would stop:

| Command | Logs stopped | | Command | Logs stopped |
|---|---|---|---|---|
| `eststo` | 100 | | `tsset` | 33 |
| `xtset` | 85 | | `postutil` | 31 |
| `project` (user-written) | 85 | | `logit` | 26 |
| `import` | 55 | | `xi` | 25 |
| `insheet` | 53 | | `destring` | 24 |
| `twoway` | 45 | | `matrix` | 23 |
| `recode` | 41 | | `u` (`use`), `so` (`sort`) | 23, 18 (both abbreviations now accepted) |

A log is stopped by its first unknown command only; known commands may still print
differently. Counts are logs, not packages: one package can hold many logs.

## Harvard Dataverse (anonymous API, no account, no terms click)

From the file search index (`corpus/census_dataverse.py`, phase `search`):

| Measure | Count |
|---|---|
| `.do` files indexed by name | 47,535 |
| `.log` files indexed | 10,923 |
| `.smcl` files indexed | 1,288 |
| Datasets with at least one do-file | 12,528 |
| Datasets with a `.log` | 2,056 |
| Datasets with a `.smcl` | 713 |
| **Datasets with a do-file and a log or smcl** | **1,287** |
| Log/smcl files in those datasets | 3,022 (16 restricted) |

The coarse classification of these datasets (Stata log or not, data present
and unrestricted, dataset licence) is the table under "Answer so far". Not yet
known: which logs pass the eligibility pass, and the terms of each file. A dataset's archive-level terms (Dataverse defaults to CC0
1.0) do not settle the terms of each file: authors often license code, results
and data separately. Licences are therefore recorded per file.

Not counted above: packages uploaded as a single zip. The search index does
not look inside zips. Listing them with byte-range requests is the next census step.

## Zenodo (anonymous API)

- `restud-replication` community (Review of Economic Studies): 560 records,
  licence CC-BY-4.0 on the records seen. Some records have no public files.
  Packages are zips; contents listed by range requests (`corpus/census_zenodo.py`).

## openICPSR (AEA journals and others)

Anonymous download is refused (HTTP 403 on project pages). Downloading needs a
signed-in account and acceptance of ICPSR's terms, which we have not done and
have not read. Dataverse alone looks large enough for now.

## Usability rule for a test case

A log becomes a case when (1) it is a Stata text log (SMCL later), (2) the
do-file that wrote it is in the package, (3) every input file it reads is
public in the package, and (4) the licence of each file it uses is recorded.
Whatever the licence, this repository ships no author log, data or do-file: a
case is a pointer (archive, persistent id, file id) plus SHA-256 hashes, and
the harness fetches the files at test time.

## First case

`tests/cases/open/dv-HNPXO1-15_figure_a1.json`: doi:10.7910/DVN/HNPXO1, a China
Economic Review package. Its `LICENSE.txt` splits the terms: author do-files
MIT (section 1); documentation, data compiled from public inputs and the logs
in `output/` CC BY 4.0 (section 2); third-party data under their sources'
terms (section 3); anonymised datasets derived from restricted data, including
`data/analytical/final.dta`, for replication only, with no redistribution
(section 4). The archive-level CC0 waiver does not override that file. 6 of 6
commands match.
Lesson from the same package: a data-construction do-file
(`05_party_secretary.do`) reads restricted raw data, so input availability must
be judged per do-file, not per package.
