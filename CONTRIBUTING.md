# Contributing

Thank you for helping. Three things make a contribution mergeable.

## 1. Sign off every commit (Developer Certificate of Origin)

Add a `Signed-off-by` line to each commit:

    git commit -s -m "tabulate: support the column option"

The line certifies the Developer Certificate of Origin 1.1
(<https://developercertificate.org/>): you wrote the change, or you have the
right to submit it under this project's licence. We merge no commit without
it. There is no separate contributor licence agreement; your contribution is
licensed under Apache-2.0 like the rest of the project.

## 2. Follow the clean-room rules

Rules 1 to 3 in `README.md` matter most:

- Never install, run, trial or remotely use Stata or any StataCorp program,
  including to check an output.
- Never read or copy StataCorp files (`.ado`, `.mata`, `.sthlp`, `.dlg`,
  datasets).
- You may read public documentation to learn what a command does, and cite it
  by URL. Do not paste manual or help text into code, comments, tests, issues,
  commit messages or AI prompts, and do not save it on your machine. Write in
  your own words.

To learn what output should look like, use a published replication package:
its authors' log is the reference.

## 3. Bring a test with its source

A new command or option comes with a test. If the test comes from a
replication package, add a case file under `tests/cases/` recording the
archive, DOI, version, licence, retrieval date and the SHA-256 of every file
used. Do not commit the authors' data, logs or scripts: the harness fetches
them at test time.

An estimator also needs a note in `docs/estimators/`: the algorithm, the
source it comes from, and how its results compare with at least one other
implementation.

If we cannot trace where a piece of code or text came from, we cannot merge
it, however good it is.
