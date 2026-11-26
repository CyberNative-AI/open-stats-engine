# esttab to CSV

Source of the layout: the authors' published CSV files and logs, HNPXO1
(doi:10.7910/DVN/HNPXO1, version 1.0). The 12 files are pinned in
`tests/esttab_expected.json` (Dataverse file id, sha256, the path the do-file
writes). The package's source code was not read.

## What is built

One call shape, from the 15 calls in the do-files:

    esttab m1 m2 ... using FILE.csv, replace mtitle(m1 m2 ...) se b(%12.4f)
        star(* 0.1 ** 0.05 *** 0.01) s(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress nogaps

All of `replace mtitle se b star s compress nogaps` must be present with
these values (`compress` and `nogaps` change only the screen table, not the
CSV). Models must be stored `reghdfe` estimates. Otherwise `Unsupported`,
which exits 2.

## File format (read from the 12 files)

- Every cell is written `="text"`, cells joined by `,`, lines end in `\n`
  (no `\r`), the file ends with a newline.
- Line 1: empty cell, `(1)` ... `(k)`. Line 2: empty cell, the mtitle words.
- Per coefficient two lines: the coefficient and, on the next line with an
  empty first cell, `(standard error)`. Both `%.4f`. A negative value that
  rounds to zero keeps its sign (`-0.0000`).
- Stars follow the coefficient: two-sided p of t = b/se with that model's own
  `e(df_r)` (clusters - 1); p < 0.01 `***`, < 0.05 `**`, < 0.1 `*`.
- **Base levels and omitted columns** (absorbed by the fixed effects) are
  rows too: `0.0000` over `(.)`, no stars. Every level of a factor shows,
  including the base (`0.zone`, `1.tier`); an interaction shows every level
  combination (`0.zone#0.after` ... `1.zone#1.after`, `0.after#c.span`).
- A name a model does not have is `=""` over `=""`.
- Row order: each model's names in its own order; a name first seen in a
  later model goes after all names seen so far, `_cons` stays last.
  (Pinned by the authors' tables 2 and 3, where regressors that first appear
  in model 2 land after every row of model 1 and before `_cons`. In our own
  example: if model 1 has `zone` and model 2 adds `span`, the rows are `zone`,
  `span`, `_cons`.)
- Footer: `N` (`%9.0f`, no padding), `r2_a` (`%9.4f`), then
  `Standard errors in parentheses` and `* p<0.1, ** p<0.05, *** p<0.01`.

## Not implemented

Other options or values (`t`, `p`, `label`, `keep`, `drop`, `order`,
`star()` with other cut points, other `b()` or `s()` formats), titles with
quotes, models from other commands, `esttab` to the screen or to other file
types, `using` a directory that does not exist (the real error text is not
pinned), `append`. A model name with no stored estimate also raises
`Unsupported` (our choice; the vendor program would stop with an
error, text not pinned).

## Needs `e()` from the estimator

`reghdfe` stores `_fullnames` (every coefficient name including base levels,
in varlist order, from `fvars.full_names`) next to `_colnames`/`_b`/`V`.
