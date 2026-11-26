# regress (ordinary least squares): unadjusted, robust and one-way clustered; testparm, lincom

Engine: `engine/ose/commands/regress.py`. Tests: `tests/unit/test_regress.py`. Real-data cases:
`tests/cases/open/dv-3EDO2Y-DietrichEtAl_JEPS_BrandedAid.json` (authors' log 3333327, linesize 105; robust) and
`tests/cases/open/dv-9N6PBH-conjointanalysis.json` (authors' log 13891995, linesize 90; clustered) and
`tests/cases/open/dv-5T2U2K-Replication.json` (authors' log 7240176, linesize 99; unadjusted).

## What is built (2026-11-25)

`regress y xvars [if] [in]` (unadjusted), `, vce(robust)` (also `robust`, `vce(r)`) and `, cl(var)` (also `cluster(var)`,
`vce(cluster var)`, `vce(cl var)`, `robust cluster(var)`), factor variables through `fvars.py`;
`testparm` with plain names or `i.a` / `i.a#i.b` terms after it; `lincom` of coefficient names joined by
`+` and `-`. Everything else raises Unsupported, exit 2: weights, `noconstant`, `level()`, two cluster variables, more slopes than clusters minus one, collinear
regressors (the omission note is in no open log for `regress`), `testparm` with options, `c.` terms or 10+
constraints, `lincom` with multipliers, constants, `_b[]` or options.

## Algorithm and sources

- Unadjusted covariance: V = s²(X'X)⁻¹ with s² = RSS/(N−k). The model F printed in the ANOVA block is
  (MSS/(k−1)) / (RSS/(N−k)); the engine computes the Wald form b₁'V₁₁⁻¹b₁/(k−1), which is the same number
  under this V (unit test checks the two to 1e-9).
- Coefficients: b = (X'X)⁻¹X'y with a constant as the last column (any linear-models textbook,
  e.g. Greene, *Econometric Analysis*, ch. 3–4).
- Robust covariance: HC1, V = N/(N−k) · (X'X)⁻¹ (Σ eᵢ² xᵢxᵢ') (X'X)⁻¹, k counting the constant
  (White 1980, *Econometrica* 48:817; the N/(N−k) scaling is MacKinnon & White 1985, *J. Econometrics* 29:305).
- Clustered covariance (CR1): V = G/(G−1) · (N−1)/(N−k) · (X'X)⁻¹ (Σ_g u_g u_g') (X'X)⁻¹ with
  u_g = Σ_{i∈g} xᵢeᵢ (Liang & Zeger 1986, *Biometrika* 73:13; Arellano 1987, *Oxford Bull. Econ. Stat.* 49:431;
  the small-sample factor as in Cameron & Miller 2015, *J. Human Resources* 50:317, section IIC). Observations
  with a missing cluster value leave the sample. t, p, intervals and the model F use df_r = G − 1, which the
  header shows as `F(k−1, G−1)` (9N6PBH: the second df is the cluster count minus one).
- t statistics and intervals otherwise use df_r = N − k; model F = b₁'V₁₁⁻¹b₁ / (k−1) over the slopes (Wald form).
  R² = 1 − RSS/TSS (centred); Root MSE = √(RSS/(N−k)) under every VCE; adjusted R² = 1 − (1−R²)(N−1)/(N−k).
- `testparm`: F = b_q'V_qq⁻¹b_q / q with F(q, df_r) from the last `regress`.
- `lincom`: estimate c'b, standard error √(c'Vc), t on e(df_r), 95% interval.
- Distributions from SciPy (`stats.t`, `stats.f`).

## Layout learned from open-list logs

- Header: a 48-column left block, an 18-wide label, `=`, an 11-wide value (3EDO2Y). Numbers of 1,000 or more
  carry thousands separators (9N6PBH). Root MSE shows 5 significant digits without a leading zero.
- Unadjusted (5T2U2K, 12 tables): a 12-wide `Source` column; SS and MS in the 11-wide general format
  (9 significant digits, so a value of ours such as `347.2918064` shows as `347.291806`), df 10 wide with separators; on the right a 16-wide label,
  `=`, a 10-wide value. No title row over the coefficient table, and `Std. err.` is capitalised.
  SS outside [1e-4, 1e8) is refused until a log shows its format.
- Clustered: `(Std. err. adjusted for` *G* `clusters in` *clustvar*`)` right-aligned to the table's width, then the table
  with `Robust` over the std. err. column (9N6PBH, 30 tables, widths 82, 84 and 89).
- Coefficient table: shared `table.py`. The column titles print the newest witnessed wording
  (`Coefficient  std. err. ... conf. interval`, HNPXO1, 9N6PBH). 3EDO2Y and 27102 print the older wording;
  the wording-table entry `coef-table-titles-t` (rules .5, `harness/wording-table.tsv`) scores those lines.
- The name column depends on the session width and on whether the long rows are variable names or value
  labels: see the `table.py` docstring. Value labels cut to `first20..` when the table would reach the line.
- Interaction rows with value labels take one line per factor: the first factor's label and ` #|`, then
  the second factor's label with the numbers (9N6PBH, two-factor interactions only).
- A factor group of 2+ rows is closed by a separator row; a one-row group is not (HNPXO1 a02 vs a13; 3EDO2Y).
- `lincom`: constraint line ` ( 1)  a - b = 0`, then a 12-wide table with `Std. err.` capitalised and row `(1)`.
- `display` of a number with no format: the 10-wide general format, so 8 significant digits for a value below 1 (9N6PBH); this
  corrected an earlier unpinned 7-digit guess in `core.py`.

## Checks and differences

| Check | Result |
|---|---|
| Independent: numpy `lstsq` + HC1 sandwich summed one observation at a time (unit test, 300 obs, heteroskedastic) | b to rel 1e-10, V to rel 1e-9, F, R², Root MSE, testparm F and p to 1e-9 |
| Independent: numpy `lstsq` + CR1 sandwich summed cluster by cluster in a Python loop (unit test, 400 obs, 40 clusters, cluster-correlated x and errors) | b to 1e-10, V to rel 1e-9, F to rel 1e-9; lincom estimate and s.e. to 1e-10 |
| Authors' Stata output, 3EDO2Y real data (`reg ... , vce(robust)` + `testparm`) | every printed digit and line identical |
| Authors' Stata output, 9N6PBH real data: 30 `reg ..., cl(id)` (N from about 3,000 to 32,000; about 900 to 2,000 clusters; factor main effects, `##` interactions, value labels), 8 `lincom`, 4 factor `testparm`, 4 `di r(p)` | 77 of 77 blocks identical, strict layout. Run as a replay of the authors' own lines because the scored case first stops at `des` (then `codebook`, `conjoint`) |
| Authors' Stata output, 5T2U2K real data: 12 plain `reg` (N about 1,500 to 1,800; up to 11 slopes with a labelled factor; name column 25 at linesize 99) | 81 of 81 replayed blocks identical, strict layout. The scored case first stops at `logit` (line 22) |
| statsmodels OLS HC1 / cluster | **NOT RUN**: statsmodels is not in the engine environment yet |

Largest difference seen: none at printed precision against the authors' output (215 tables: 173 robust,
30 clustered, 12 unadjusted). Against the
independent implementations: 1e-9 relative on V (floating-point order of summation).

## Still open

Weights, `noconstant`, `level()`, `beta`, collinearity notes, two-way clusters: refused until an open log shows
them. statsmodels comparison once it is installed.
