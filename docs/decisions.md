# Architecture decision record

Decided 2026-11-24. Revisit triggers are
listed with each choice. Later changes are added as dated entries at the end.

## 1. Implementation language: Python 3 with NumPy and SciPy

The engine is a Python package (`engine/ose`, working name). Python runs the
interpreter, the commands and the output layer. NumPy holds the data and
SciPy supplies special functions and distributions.

Why: the work is thousands of small commands checked against real logs, so
the speed of writing a correct command matters more than raw speed at the
start. NumPy's float32 type gives exact `float` storage rounding (a common
source of wrong digits). LAPACK through NumPy is a well-tested numeric base.
Python also runs in the browser through Pyodide with NumPy and SciPy included,
so one code base serves the laptop, CI and the browser.

Rejected:
- **Rust compiled to native and WebAssembly.** Fastest, and the best browser
  story, but three to five times slower to write per command, no linear
  algebra library as mature as LAPACK in the browser, and no Rust toolchain on
  the host today. Kept as the plan for hot kernels (see trigger).
- **TypeScript.** Runs in every browser with no runtime download, but no
  dependable linear algebra or distribution library, and float32 handling is awkward.
- **R or Julia as host.** Mature statistics, but R's own semantics leak into
  results, the browser builds (webR, Julia WASM) are heavier or immature, and
  both narrow the contributor pool.
- **C or C++.** Fast and portable to WASM via Emscripten, but slow to write
  and easy to get memory errors in, with no gain over Rust.

Revisit when a corpus case takes more than ten times its author's reported
runtime, or the browser page cannot load in under 15 s on a normal laptop.
Then move the hot kernel (sorting, group operations, fixed-effect absorption)
to Rust exposed to Python, not the interpreter.

## 2. Data layer

One in-memory dataset of typed columns. Numeric columns are float64 arrays
using the `.dta` double encoding of missing values: system missing is 2^1023
and `.a`–`.z` follow it. These values are finite and larger than any valid
number, so comparisons order missing values exactly as the language does
without special cases. Each column keeps its storage type (byte, int, long,
float, double, strN, strL); assigning to a `float` column rounds through
float32. Strings are object arrays. Value labels, variable labels, formats,
characteristics and the sort order travel with the dataset. The `.dta` reader
covers formats 113–115 and 117–119 and the writer produces format 118. Both
are written from the published file layout.

Rejected: pandas (its own missing and type rules would have to be undone
everywhere), Arrow (good for scale, but no extended missing values and no
float32 rounding rules; may back large data later).

## 3. Numeric core

NumPy/LAPACK for linear algebra, SciPy for distributions. Each estimator
records in `docs/estimators/<name>.md` the algorithm used, its source, the
independent implementation it was compared with (statsmodels, linearmodels,
R's fixest or a closed form), and the largest difference seen. A command
that meets a case it does not handle raises "not implemented". It never
prints a number it is not sure of.

## 4. Language front end

Hand-written, in two phases, as the language itself works:
1. `lexer.py` turns do-file text into logical lines (comments, `///`
   continuation, `#delimit ;`) and keeps the physical lines for the log echo.
2. At execution time `macro.py` expands locals, globals, `=exp` and extended
   functions. The interpreter then reads prefixes (`capture`, `quietly`,
   `by`) and dispatches the command, which parses its own arguments with the
   shared splitter (`syntax.py`: varlist, `if`, `in`, weights, `using`,
   options with minimum abbreviations). Expressions use a Pratt parser
   (`expr.py`) whose trees are cached and evaluated as whole-column NumPy
   operations. `by` groups supply `_n`, `_N`, subscripts and running sums.

Rejected: a parser generator (ANTLR, Lark). Macro expansion changes the token
stream at run time and every command has its own syntax, so a single grammar
does not fit and would have to be bypassed constantly.

## 5. Output and matching

Output is produced by our own formatter: display formats (`%9.0g`, `%9.2f`,
`%12.0fc` and others) and per-command layouts. Layouts are learned from
published logs and pinned by tests taken from corpus cases, never from the
vendor's text. The harness compares the engine's log with the author's log
under `docs/matching-rules.md`: unwrapped, block by block, token by token,
numbers within one unit of the last digit shown.

**Results tables (`esttab`).** `esttab` belongs to a community
package, not to the vendor; its layout is learned from the authors' CSV files
(HNPXO1, 12 files) and the log line `(output written to FILE)`, and compared
byte for byte by `harness/csvcompare.py`. One call shape is built: `esttab
<stored reghdfe estimates> using FILE.csv, replace mtitle() se b(%12.4f)
star(* 0.1 ** 0.05 *** 0.01) s(N r2_a, fmt(%9.0f %9.4f %9.4f)) compress
nogaps`. Any other option, option value, target type, missing estimate or
estimator raises `Unsupported`. Details and the rules read from the files:
`docs/estimators/esttab.md`.

## 6. Browser build

The same package runs in Pyodide inside a Web Worker. The page loads Pyodide
with NumPy and SciPy, installs the engine wheel, mounts the user's do-file and
data in the in-browser file system, runs it and shows the log. Nothing is
uploaded. The engine exposes one function
`run(dofile_text, files) -> log_text` (`engine/ose/web.py`; `run_with_svg`
also returns SVG exports and the exit code).

Measured 2026-11-24 (`web/MEASUREMENTS.md`): **go.**
First load 30.2 MiB (SciPy's wheel is 16.4 MiB of it); cold start to ready
5.5 s median in Chrome, 7.2 s in Firefox, loopback, desktop; warm run of the
100-observation example 7-11 ms; peak memory 0.6 GB Chrome, 1.5 GB Firefox.
Under the 15 s revisit trigger on a laptop with ordinary broadband; at 10 Mbit/s
the download alone is about 25 s. Not measured: phones, a real network.
Pyodide 0.29.4 ships SciPy 1.14.1 and NumPy 2.2.5, older than the native
build; the conformance suite runs natively, so a browser-only numeric
difference would go unseen until the harness also runs under Pyodide.
The public page never serves an author's data file, and its public build
contains none. The local workspace (`web/serve.py`) differs on purpose: on
loopback only, and only when the user opts in (`web/build.py
--with-replication-data`, then `web/serve.py --with-replication-data`), it
fetches the authors' replication dataset from its archive to the user's own
machine and serves it to the user's own browser, for personal replication
under the authors' terms. No public build contains that dataset or that route.

## 7. Corpus and scoring

Cases are JSON pointers (archive, DOI, file IDs, licence, hashes) in
`tests/cases/<set>/`. Files are fetched at test time into a local cache
(`$OSE_CACHE`, default `~/.cache/open-stats-engine`), never stored in git.
`harness/run.py` writes the score file; dated scores are published separately.

## 10. Imported decimals take the session's default type (2026-11-25)

`import delimited` and `insheet` store a column with any non-integer value as
the session's default numeric type: `float` (rounded) unless `set type double`
is in effect, in which case `double`. This is the rule `generate` already uses.
Integer columns keep the narrowest exact type; integers beyond `long` keep the
earlier exact-`float`-else-`double` rule, which no published log witnesses yet.
Decimals beyond the `float` range refuse under the default type.

Evidence: PXAPMY (log 10539699, CSV 10539698) prints the final `zinb` log
pseudolikelihood to 5 decimals. We fitted each storage choice with an
independent NB2-plus-logit implementation (SciPy, not the engine). Each
reference fit stopped at a local maximum: max |gradient| <= 2e-7 and a
negative-definite Hessian. Under the previous rule (decimals `double`, `gen`
`float`), the reference fit's log likelihood rounds below the printed value in
model 1 (short by 9.6e-7) and model 12 (short by 1.9e-7). With decimals as
`float`, the reference fits print the authors' digits in all 11 blocks they
cover. With everything `double`, the reference fits also do; this is why
`set type double` stays available. This is numerical evidence from local
maxima, not a bound: we have no global upper bound for the zero-inflated
likelihood, so a fit we did not find could in principle reach the printed
values under the previous rule. MOAKFJ and ALS5GH cannot discriminate
(decimals arrive through `destring`, or none exist). Limits: one reference
implementation; model 12's margin needs it accurate to 1e-7. Reopen if a
second independent fit moves either value across its interval, or a
published log shows imported decimals with digits `float` cannot hold.

Precision: `set type double` stores the nearest binary64 value, which holds
15 to 17 significant decimal digits, not every digit a long decimal writes.
The reader checks integer tokens against the type that stores them. `float`
holds every integer up to 2^24 (16,777,216) and `double` up to 2^53
(9,007,199,254,740,992). An integer token that writes a digit its stored value
loses refuses in any notation: `9007199254740993` and `9.007199254740993e15`
in any column, and `16777217` in a `float` column with decimals. A token such
as `3.5e38`, whose written digits a `double` keeps, reads. `float` is chosen
only inside its range (magnitude up to about 1.70141173e38); larger `float`
encodings are missing values in a `.dta` file, so such integers stay `double`.
