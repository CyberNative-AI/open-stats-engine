# collapse

**Status (2026-11-24):** built in `engine/ose/commands/shape.py`. `reshape` was added later in the same file.

## Algorithm

Rows outside `if`/`in` are dropped; with `cw`, rows missing any source variable too. Rows are
stable-sorted by the `by()` variables; each group yields one row. Each statistic uses the group's
non-missing values of its source variable, in data order:

| Statistic | Rule | Empty group |
|---|---|---|
| mean, min, max | arithmetic mean, smallest, largest | missing |
| sum, rawsum | sum (equal without weights) | 0 |
| count | number of non-missing values | 0 |
| sd, semean | sample sd with n−1; sd/√n | missing if n < 2 |
| median, p1–p99, iqr | the summarize percentile rule (`commands/summ.py:pctile`) | missing |
| first, last | first/last row of the group, missing or not | — |
| firstnm, lastnm | first/last non-missing value | missing |
| percent | 100 × group count / count over all used rows | — |

Result order: by-variables, then results in the order written. Labels: `(stat) <source label or name>`.
Refused loudly: weights, `sebinomial`/`sepoisson`/`cv`, string sources, `reshape`.

## Storage types: INFERRED, not yet witnessed

count → long; sum/rawsum → double; min, max, first, last, firstnm, lastnm → source type and
format; every other statistic → double if the source is double, else float. No log on the open
set yet `describe`s collapsed data, so this is unconfirmed. Float storage rounds later output, so
a wrong choice would show as WRONG on a later command. **Confirm or correct it from the first
open-set log that describes or lists collapsed data with full precision.**

## Checks

- `tests/unit/test_shape.py`: hand-computed groups, the missing-value rules, refusals.
- Independent implementation: a plain-Python dict/loop reference, written apart from the engine,
  for mean/sum/count on 400 random rows across 9 groups. Agreement within a relative 1e-12. No
  pandas or R in the engine's environment; a statsmodels/R cross-check is NOT RUN.
- Authors' logs: `dv-R7RYIV-table6and7` and `dv-R7RYIV-table_appendix5and6` (doi:10.7910/DVN/R7RYIV,
  CC0, IPUMS-derived microdata fetched at test time). Every command from the collapse at do-file
  line 24 through line 169 matches, including the `replace ... (27 real changes made)` counts that
  depend on the collapsed rows (one row per region × birth year). Both stopped at `append`, which was not yet built.
