# Estimator record: `reghdfe` (linear regression absorbing several fixed effects)

Status 2026-11-24. `reghdfe` is a community command (Sergio Correia,
MIT licence), not a StataCorp program. No `.ado`/`.mata` source of it was read; the method comes from the
papers below and the output layout from published logs (clean-room rule 4).

## What is implemented

`reghdfe depvar indepvars [if] [in], absorb(v1 v2 [v3 ...]) cluster(c) | vce(cluster c)`, two or more
plain absorbed variables (numeric or string), one-way clustering, factor variables `i.` `c.` `ib#.` and `##`.
One lone `c.x#i.g` or `i.g#c.x` is supported when neither variable occurs in another term, the factor is
unlabelled, and the continuous variable is constant within an absorbed effect on the estimation sample.

`allbaselevels` displays the reference level of each main-effect factor in sorted level order, with `0 (base)`.
The two HNPXO1 Figure 4 models establish the base-row layout, including how a long value label is abbreviated.
The option requires a model without factor interactions. Base rows affect only the printed table.

Refused with `not implemented` (no log pins them yet): one absorbed variable, unadjusted or `vce(robust)`
standard errors, multi-way clustering, weights, `absorb()` with interactions or saved FEs, other lone
interactions, other collinearity among regressors, a continuous regressor or single interaction column
collinear with the fixed effects, factor-level labels longer than 11 characters.

### Lone slope interaction

The [HNPXO1 replication package](https://doi.org/10.7910/DVN/HNPXO1) pins this case in Table 4 models 1
and 2. A lone interaction creates one `x * (g == level)` column for every observed level, including the
lowest. Their sum is `x`. In these models `x` is constant within firm, so the sum lies in the absorbed
firm effects. The engine checks that identity on the final estimation sample, partials every column,
then omits the highest level before fitting. The stored coefficient and covariance entries for the
omitted level are zero. A remaining rank deficiency still stops execution.

## Algorithm and sources

| Step | What we do | Source |
|---|---|---|
| Sample | complete cases on depvar, regressors, absorbed and cluster variables, then `if`/`in` | |
| Singletons | drop observations alone in any FE group, repeat until none | Correia (2015), *Singletons, cluster-robust standard errors and fixed effects: a bad mix* |
| Partialling | symmetric Kaczmarz sweep (demean FE 1..G, then G-1..1) as the operator T; conjugate gradient on (I - T)x = (I - T)y, all columns at once | Correia (2017), *Linear models with high-dimensional fixed effects: an efficient and feasible estimator*; Hernández-Ramos, Escalante and Raydan (2011) |
| Stopping | sqrt(alpha_k ||r_k||² / remaining_k) <= 1e-8 for every column, remaining_0 = y'y (raw), remaining_k = remaining_{k-1} - alpha_k ||r_k||² | Hestenes and Stiefel (1952) error estimate |
| Collinear with FEs | partialled sum of squares / centred sum of squares < 1e-9: coefficient omitted, note printed | |
| Coefficients | OLS on partialled data; constant = mean(y) - mean(X)b | Frisch-Waugh-Lovell |
| VCE | CR1 sandwich on [partialled X + mean(X), 1], scale (N-1)/(N-K) · G/(G-1) | Cameron and Miller (2015) |
| t, CI, F | t with G-1 df; Wald F on the slopes with (k, G-1) df | |
| Redundant FE levels | connected components of the bipartite graph of two FEs | Abowd, Creecy and Kramarz (2002) |

### Degrees of freedom (learned from HNPXO1 logs, four cluster choices)

- An FE whose every group lies in one cluster is **nested**: all its levels redundant, marked `*`.
- Among the rest, in order: the first gives up 1 level if any FE was nested, else 0; the second gives up its
  connected-component count with the first (exact); later ones the largest count against any earlier
  non-nested FE, marked `?` (lower bound).
- K for the VCE scale = sum of Num. Coefs + k + (1 if any FE nested). Without nesting the constant lives in
  the first FE and is not counted again.
- Root MSE and adjusted R² use N - k - sum(Num. Coefs) - sum(levels of nested FEs).

## Independent checks and the largest differences seen

| Check | Result |
|---|---|
| Authors' published output, HNPXO1 `02_table2_baseline` (4 models, cluster id) | every printed digit matches (coefficients, SEs, t, p, CIs, F, R², within R², adj. R², Root MSE, DoF table, singleton and iteration counts) |
| Authors' published output, HNPXO1 `04_table4_robustness` (models 1 and 2, lone slope) | all 32 fitted year coefficients match the printed values, with 2014 omitted in both models. Model 1's 1999 lower confidence bound differs by 1e-7, within the harness tolerance. |
| HNPXO1 `05_table5_clustering` blocks with cluster countycode (nothing nested), citycode (two nested), industrycode (second FE nested), run from a scratch driver | every printed digit matches; these three fixed the no-nesting constant rule (the alternative missed SEs in the 5th digit) |
| HNPXO1 open set, 17 cases | every `reghdfe` block the engine ran matched; 0 WRONG |
| Iteration counts | all four printed counts in table 2 match; the stopping rule was chosen on models 1 and 4 and then predicted models 2 and 3 |
| Explicit dummy-matrix least squares (`tests/unit/test_reghdfe.py`, no partialling code shared) | slopes within 1e-6; cluster SEs within 1e-6 relative |
| statsmodels / R fixest | **NOT RUN**: neither is in the engine environment; not yet installed. Next check. |

Known limits: the redundancy rule for three or more non-nested FEs is a lower bound by construction (as the
logs mark it); the iteration count depends on floating-point order and could differ by one on other data.
If a held-out case shows that, the count is the first thing to look at.
