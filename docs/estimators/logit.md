# logit (binary logistic regression, maximum likelihood, default covariance)

Engine: `engine/ose/commands/logit.py`; z variant of the table in `engine/ose/table.py` (`print_table(..., stat="z")`).
Tests: `tests/unit/test_logit.py`. Real-data evidence: open-list package 5T2U2K, authors' `Replication.log`
(file 7240176, linesize 99; 8 `logit` blocks, 8 distinct models) and `Replication_Appendix.log` (file 7240177;
28 `logit` blocks, 26 distinct models, plus 2 blocks from another command that fits a logit inside it).
Counts of what was replayed and what matched are under "Checks and differences".

## What is built (2026-11-25)

`logit y x1 x2 i.f [if] [in]` with factor variables through `fvars.py`: iteration log, header, z table,
stored `e(N) e(ll) e(ll_0) e(r2_p) e(chi2) e(p) e(df_m) e(rank) e(converged) e(ic) e(b) e(V)`.
Everything else raises Unsupported, exit 2: `robust`, `vce()`, `cl()` (not built yet: see "Not built"), weights, `or`, `offset()`, `constraints()`, `noconstant`, `level()`, collinear regressors,
an outcome other than 0 and 1, a perfect predictor (any column whose non-zero cells share one outcome, or a
coefficient above 20 in absolute value), non-convergence, a log likelihood of 1e5 or more in absolute value.

## Algorithm and sources

- Model: P(y=1|x) = 1/(1+exp(-xb)); log likelihood Σ y·xb − log(1+exp(xb)) (Greene, *Econometric Analysis*,
  ch. 17; Cameron & Trivedi, *Microeconometrics*, ch. 14). Constant is the last column.
- Starting values: slopes 0 and constant log(ȳ/(1−ȳ)). Iteration 0 is that log likelihood, which is also
  `e(ll_0)` (the authors' `LR chi2` and `Pseudo R2` agree with it to the digits printed).
- Direction: d = (X'WX)⁻¹X'(y−p), W = diag(p(1−p)), i.e. Newton–Raphson, the same step as IRLS.
- Convergence: stop after the first iteration whose log likelihood moved by less than 1e-7 of its own size
  (relative). That iteration is printed. A move that small usually does not reach the printed digits, so in most
  blocks the last two iteration lines show the same value. When the final move is close to the limit it shows in
  the last printed digit: in the authors' logs the last value changes in 1 of the 8 primary blocks and 2 of the 28
  appendix `logit` blocks, with final moves of 1.9e-8 to 3.5e-8 relative. All three are among the blocks the
  engine reproduces line for line. In every one of the 36 blocks, the printed values put the last move below 1e-7
  and the move before it at or above 1e-7.
- Covariance: V = (X'WX)⁻¹ at the final b. z = b/se, P>|z| from the normal tail, interval b ± 1.959964·se.
- LR chi2(k) = 2(ll − ll_0), k = number of non-constant columns; Prob > chi2 from the χ² tail with k df;
  Pseudo R2 = 1 − ll/ll_0. Distributions from SciPy (`stats.norm`, `stats.chi2`).

### Step rule: two were tried (stop-rule record)

| Rule | What it does | Authors' iteration logs reproduced |
|---|---|---|
| 1. Plain Newton | full step s = 1; halve s if the log likelihood falls | 4 of 8 in `Replication.log` |
| 2. Newton with 1/8 expansion (built) | s = 1; if the log likelihood falls, halve; otherwise keep adding 1/8 to s while it still rises | 8 of 8 in `Replication.log`; 20 of the 20 replayed appendix blocks |

Rule 1 misses 4 of the 8 iteration logs, in the third to fifth significant digit of iterations 1 to 3, with
coefficients and tables identical under both rules. The authors' first step on the one-regressor model of the
first outcome lies on the Newton direction at 1.375 times its length (found by solving for the step that gives
their iteration 1; continuing Newton from there reproduces their iteration 2 to all printed digits), and on the
second outcome at 1.125 (their value equals the maximum along the direction). Steps of 1/8 up to the point where
the next 1/8 stops helping reproduce every step in the 8 + 20 replayed blocks, including the second iteration of two covariate
models (s = 1.125) and the steps where s = 1 (the next 1/8 would lower the value). This is an empirical rule
fitted to those logs: the decimal digits are identical, the mechanism of the vendor's search is not known, and a
log with a different step pattern may need a third rule. The digits per model are not reprinted here: they are
compared against the fetched log (authors' log text is not redistributed).

## Layout learned from the logs

- `Iteration k:   log likelihood = ` then the value right-aligned in 10 columns in the automatic 9-significant-digit
  form (`-123.45678`, `  -123.456` when trailing zeros drop), two trailing spaces; a blank line before and after the block.
- Header: `Logistic regression` in a 56-column left block; `Number of obs =` with a 6-wide value (thousands separators);
  `LR chi2(k)` 2 decimals, `Prob > chi2` 4, `Pseudo R2` 4; `Log likelihood = ` (same format as the iterations) in
  the left block of the fourth line.
- Table: `Coefficient  Std. err.      z    P>|z|     [95% conf. interval]`, capital-S `Std. err.`, no VCE row, same widths
  as the t table (shared `table.py`).
- The name column widens for a 13-character dependent variable when every row label is shorter
  (79-column table in 5T2U2K). A 28-character dependent variable in the same package does not widen it: it is
  abbreviated to the row width. Only 13 is witnessed.
  `name_width` got a `depvar` argument; `regress` passes it too, so its clustered note stays aligned with the table.

## Checks and differences

| Check | Result |
|---|---|
| Authors' 8 blocks of `Replication.log` on `Data_Officers_replication.dta`, line by line | 8 of 8 identical (replay script; `tests/unit/test_logit.py::test_authors_eight_logit_blocks_are_identical` repeats it when the cache is present) |
| `Replication_Appendix.log`, 28 `logit` blocks (26 distinct models), each replayed alone on the same file (2026-11-25) | 20 identical. 8 not compared: 4 use a sample-marker variable the do-file makes earlier with commands the engine does not yet run; 4 printed an iteration 0 log likelihood that differs from the replay on the full file, so they ran on a different sample (inferred: earlier steps of the do-file change the data; not traced). The 2 blocks from another command that fits a logit inside it were not replayed |
| IRLS written independently (weighted `lstsq` per iteration, 200 iterations) on the 8 real models | largest difference: b 4.4e-7 (the engine stops at the 1e-7 relative tolerance, as the authors' log does; IRLS is run to machine precision), V 1.9e-8, ll 2.7e-12. On the synthetic unit-test data b agrees to 1e-8, V to 1e-9 |
| Closed form ll_0 = N(ȳ ln ȳ + (1−ȳ) ln(1−ȳ)) | agrees to 1e-9 in the unit test |
| statsmodels `Logit` | **NOT RUN**: statsmodels is not in the engine environment yet |
| Open set (`harness/run.py --set open`), rules 2026-11-24.5, wording table `37892d2eb156`, 21 cases in 5 packages, 1,551 commands | 519 → 521 matched (0.3346 → 0.3359): open-set runs generated 2026-11-25 04:32:06 UTC (before `logit`) and 05:06:13 UTC (after). The only case that changed is 5T2U2K (its first `logit` now matches; it then stops at `margins`, Unsupported). Both runs also counted the same 3 `WRONG` tempfile `save` blocks in two other cases; those are fixed separately (matching rules .6 and the `save` notes) |

What the checks cannot catch: the IRLS and the engine share one model (the logit likelihood) and one convergence idea,
so a misreading of Stata's header definitions would pass the unit test. That is why the digits are checked against
the authors' logs, but only on one data file: 28 blocks replayed identically (8 primary, 20 appendix).

## Not built

- `robust`, `vce(robust)`, `cl()`, `vce(cluster)`: the 5T2U2K logs have none. Open-list package AIZHJO (listed
  2026-11-25) has two standalone clustered `logit` blocks, with a Wald chi2 header, a pseudolikelihood line and a
  robust table label. That layout is not built yet: it will be built from that log, not printed from memory, and
  until then these options raise Unsupported.
- Perfect prediction notes, dropped-observation notes, weights, `or`, `offset()`, `constraints()`, `margins` after `logit`
  (the 5T2U2K case now stops there).
- `e(sample)`: the engine has no estimation-sample marker (a line of the appendix do-file generates a variable from `e(sample)`).
