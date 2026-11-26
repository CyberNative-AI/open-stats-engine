# Merge two of your own .dta files in the browser

Both datasets are invented for this example. `tests/unit/test_example_merge.py` checks every row below
on each change to the engine.

## What you need

- `roster.dta`: 7 people (`id`, `name`). This is the **master** file.
- `scores.dta`: 6 scores (`id`, `score`). This is the **using** file.
- The do-file under **The do-file** below.

Make the two files from the repository root with `python3 -I docs/examples/merge-two-files/make_inputs.py engine <out-dir>`.
The same engine revision always writes the same bytes.

## Steps

1. Open the local browser workspace from the pinned checkout (`web/README.md`) and wait for **Ready to run**.
2. Under **Load an example**, choose **Blank do-file**.
3. Paste the do-file below into **Do-file code**.
4. Click **Choose .dta files** and select `roster.dta` and `scores.dta` together.
   Both names should appear in the attachment list.
5. Choose **Run do-file**. The state should read **Run complete**.
6. Scroll the run log. The log box scrolls on its own, so the row lines are below the first screen.

## The do-file

```stata
use "roster.dta", clear
merge 1:1 id using "scores.dta"
count
local n = r(N)
forvalues i = 1/`n' {
    display id[`i'] " " name[`i'] " " score[`i'] " " _merge[`i']
}
tabulate _merge
count if _merge == 1
count if _merge == 2
count if _merge == 3
```

## What you should see

The merge report:

| Result | Rows | Which ids |
| --- | ---: | --- |
| Matched (`_merge==3`) | 4 | 104, 105, 106, 107 |
| From master only (`_merge==1`) | 3 | 101, 102, 103 |
| From using only (`_merge==2`) | 2 | 203, 204 |
| Total after merge | 9 | |

Then one line per row, in `id name score _merge` order, sorted by id:

```
101 Ada . 1
102 Bo . 1
103 Cy . 1
104 Dev 88 3
105 Fay 77 3
106 Gus 64 3
107 Eli 59 3
203  90 2
204  83 2
```

A `.` in the score column means the id was not in `scores.dta`. An empty name means it was not in
`roster.dta`. `tabulate _merge` and three `count if` lines repeat the 3 / 2 / 4 split.

To check it yourself: the ids in `roster.dta` and `scores.dta` that appear in both files are the
four matched rows. The ids left over on each side are the other five.

## If you change the example

- Attach two files with distinct filenames and a shared numeric key that is unique in each file.
  Update the filenames, key, and displayed columns in the do-file to match your datasets.
- Use the `forvalues` and `display` loop in the do-file to show rows. `list` stops the run with
  `This engine doesn't support list yet` (exit 2).
- The loop bound can come from `count` followed by `local n = r(N)`, as here, or from `` `=_N' ``.
  Both give 9 after this merge.
- Use `tabulate _merge` for the result counts. The two-way form `tabulate id _merge` stops the run
  with `This engine doesn't support tabulate yet` (exit 2).

## Replay evidence

Checked in November 2026: native engine and Chrome 157 (headless, signed out, loopback, offline Pyodide 0.29.4) produced the same transcript
byte for byte. The 9 row lines and all counts were compared with rows read straight from the bytes of the two input files by a
separate minimal `.dta` reader. Three fresh browser replays gave the same transcript.

Not run: Stata compatibility, mobile, the hosted page, drag-and-drop, or other input schemas.
