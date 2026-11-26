# egen: percentiles (`pctile()`, `median()`)

**Status (2026-11-25):** built in `engine/ose/commands/egen.py`. The other egen
functions and their evidence are listed in that module's docstring; this record covers the two
that compute a statistic whose value a reader could get wrong.

## Algorithm

For each group (all rows, or each `by()` combination, after `if`), take the non-missing values of
the source, sorted. With n values and percentile p (a whole number 1..99; `median()` is p = 50):

- find the smallest k with k/n ≥ p/100;
- if k/n = p/100 exactly, the result is the mean of the k-th and (k+1)-th values;
- otherwise it is the k-th value.

This is Hyndman & Fan (1996), "Sample quantiles in statistical packages", *The American
Statistician* 50(4), definition 2: the inverse of the empirical distribution function, averaged at
the jumps. It is the same rule as `summarize, detail` (`_percentile` in `egen.py`). A group with no
non-missing value gets `.` (not an extended code). Every row of the group gets the group's value,
including in-sample rows whose own source value is missing. The result is computed in double and
stored at the declared type (float by default, or `egen double`).

Refused loudly: fractional or out-of-range `p()`, string storage types, and any egen option that
no open-list log shows.

## Checks

- `tests/unit/test_egen.py`: hand-computed examples.
- **Independent comparison (a kit written by someone other than the module's author, rerun on
  2026-11-25):** 7,942 row cells over 14 generated groups. The groups include ties inside averaged
  pairs, whole and fractional ranks, `.`/`.a`, empty and singleton groups, near-max and subnormal
  values, `if`, `by()`, `bysort`, and float and double storage. On every row, grouped egen
  pctile() at the nine tested values p = 1, 5, 10, 25, 50, 75, 90, 95 and 99, and median(), equal the correctly rounded H&F definition-2 value. The value was
  checked against exact rational arithmetic written from the definition, and against numpy 2.5.5
  `percentile(method="averaged_inverted_cdf")`.
  - Double storage: 5,646 / 5,646 cells exact (0 ulp). Float storage: 2,010 / 2,010 equal the double
    result rounded to float. 286 missing cells agree. Row order, `bysort` order, storage types and
    the 36 "(N missing values generated)" lines agree.
  - **Where the references differ:** numpy averages as `b − (b−a)·½`, which is 1 ulp from the exact
    midpoint on 4 of 468 group×p values (two pairs built to show it). The engine matches the exact
    value there.
  - Planted-fault controls (never average; lerp average; `.a` for an empty group) were each caught.
  - Same result on three versions of `egen.py` from 2026-11-25 that differ only in comments.
  - The kit, its observations and its frozen rule are not shipped.

## Not established

- That the reference product uses this rule for egen percentiles. No vendor material was used. An
  authors' log that prints a grouped percentile with enough digits would settle it.
- Missing or string `by()` keys, `in`, and weights were not tested.
