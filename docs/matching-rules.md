# Matching rules

Current version: **2026-11-24.14.7**. Two implementations follow this text: the open harness
(`harness/logmatch.py`, which implements .14.7) and an independent held-out scorer, written and run by people who write
no engine code. A held-out score is labelled with the rules version its scorer implements.
Neither imports the other. A change after a scoring run needs a dated entry in the change log at the end, and a
new version; old scores keep their label.

The scored record is the engine's **transcript**, the file `python -m ose run FILE.do --transcript OUT` writes.

## 1. Denominator

- **Expected log = the authors' log.** The denominator is the commands in it. The engine cannot change it.
- A **command** is a top-level logged command block: a line starting `. `, plus its `> ` continuation lines, plus the output up to the next `. ` line.
- A loop or program call is **one** command. Its body lines (`  2.   cmd`, `  3.`) are part of its output and are compared with it. A 100-iteration loop counts once. This is stated so nobody reads the number as "executed lines".
- **Not counted:** blank commands, comments the echo proves are comments (below), `log using/close/on/off` lines the scorer reads (with or without `capture`, `quietly` or `noisily` prefixes, .11), `set more off`-style session settings (an explicit list in the tool, versioned) the scorer reads, `#delimit` directives on a line of their own, and the header and footer blocks of the log. "Reads" is defined in the next point. A `log` line or a setting whose echo the scorer does not read (for example `log close;`, which holds a `;`) is counted like any unread echo: it is in the denominator, never in the numerator, and it is `NOT_RUN` when the engine's transcript has no echo to align with it.
- **The scorer reads an echo only when every reading agrees (.13, narrowed in .14).** A command's echo is its `. ` line and its `> `
  lines. The log prints `> ` both before a new line of a continued command and before the rest of a long line
  wrapped at the line width, and the log does not say which. Nor does it always show the delimiter mode: a log can be
  opened after a `#delimit ;`. So the scorer does not work out where the do-file's lines ended or which mode was in
  force. It takes the echo's text with its `> ` lines appended, and reads it only in the cases below, which give the
  same answer under every reading (either mode, each `> ` a wrap or a new line). The kind of an echo is decided from
  its own text, and nothing from the line width. The one look past the echo is the last-statement point below, which
  reads the records after it in the same session and can only make an echo unread.
  - *Comment, not counted.* (a) The text starts with `*` (not `*/`) and holds no `/*`, `*/`, `///`, and no `;`
    except as its last character. (b) A one-line echo that starts with `//` (including `///`) and holds no `/*`,
    `*/`, and no `;` except as its last character: a continued line would have been echoed with `> `. (c) The
    text starts with `/*`, ends with `*/`, and holds exactly one `/*`, one `*/`, no `//` and no `;`.
  - *Directive, not counted.* A one-line echo that is exactly `#delimit ;` or `#delimit cr` (any abbreviation down
    to `#d`).
  - *Plain, counted, can earn credit.* (a) The text holds no `//`, `/*`, `*/` and no `;` at all, does not start
    with `*` or `#`, and has at most 8 log lines. A closing `;` is part of the command in CR mode and ends it in `;`
    mode, so an echo with a `;` is not read (.14). With no `;` the echo was not in `;` mode, because a statement
    without its `;` runs into the next do-file line, which is echoed with `> ` in the same echo. So each `> ` is a
    wrap, and the command is the text with its `> ` lines appended, nothing added. As a guard that can only withhold
    credit (a log whose wrap lines lost their trailing blanks), every way of joining the lines with or without a
    blank must give the same kind of command: the not-counted lists, the volatile lists (section 6), a `log` line
    and the `save` condition in 8.1.
    (b) A one-line echo with no `"`, `` ` `` or `;` whose only comment is one `/* */` that ends the line. The command
    is the text before it. (c) A one-line echo with no `"`, `` ` ``, `;`, `/*` or `*/`, whose only `//` (or `///`)
    follows a blank. The command is the text before it.
  - *The last statement of a do-file is not read (.14, .14.1).* The argument in (a) needs a next do-file line, and
    the scorer looks for it only in the log records that follow the echo in the same recorded session. An echo that
    would be plain is not read when those records show no next statement for it: an `end of do-file` line in its
    output or in the output of the empty prompts after it, no echo after it other than empty prompts, a `#delimit`
    directive as the next echo, or a log header or footer block before the next echo (.14.1). A log file can hold
    more than one session (closed and opened again with `append`); the first echo of the next session says nothing
    about the previous do-file. The log cannot show whether an unclosed `;`-mode statement ran there. `log` lines
    and the not-counted settings stay not counted.
  - *Output belongs to the echo before it in the same session (.14.3).* Lines after a header or footer block and
    before the next session's first echo (a log opened inside a loop prints output before its first top-level echo)
    belong to no block, as lines before a log's first echo do. They never join the previous session's last block.
  - *Anything else is not read.* It is counted (never left out, never excluded as volatile), its output is compared
    without the 8.1 join, and it earns no credit of any kind: matching output is class `AMBIGUOUS`, with no headline,
    strict or unwitnessed credit, and it never witnesses a silent block. Output that differs is still `WRONG`.
  - *A row earns credit only when the expected and the actual echo are both plain.* If either is not, the row
    follows the previous point. Whether a row is counted is read from the expected echo.
  - Alignment and the evidence keep the echo as printed.
  - *What "the same command" means here (.14.1).* Every rule above reads the echo **as the log displays it**, and
    the scorer has nothing else: it does not read the do-file. Two echoes are the same command when their displayed
    text is equal after the normalization in section 2 (runs of blanks read as one blank, absolute paths read as
    their file name). The display can lose information: a tab is shown as blanks, and blanks inside a quoted string
    are merged by the normalization. Two commands that differ only there, for example `local s "a<tab>b"` and
    `local s "a b"`, compare as the same command. So a credited row says: the displayed command agrees and its
    output agrees; for a silent command, the displayed command agrees and the witness in section 2 holds. It does
    not say that the two programs ran byte-identical command text or stored the same values. The engine and the
    authors run the same do-file, so this is a difference the scorer cannot see, not one it allows.
  - *What this costs.* A command continued with `///`, a command with a comment in the middle, a wrapped `//`
    comment, every echo with two statements, every echo with a `;` (so every statement of a log in `;` mode) and the
    last statement of a do-file are counted and not credited, even when their output matches. The
    `AMBIGUOUS` count is reported beside the score, so the work they hold stays visible. Reading them needs
    evidence the log does not carry, such as the do-file's own line breaks.
- **Excluded and reported separately (volatile):** commands whose output is defined by the clock, the machine or the RNG, listed in section 6. They leave both numerator and denominator and appear as "excluded: volatile" per package, so excluding cannot hide a failure.
- Per-case denominator is fixed when the case is sealed, from the log alone, before any engine run.

## 2. Matching one command block

A block matches when **its command text aligns and its output matches**.

- **Alignment.** Command texts are compared after collapsing whitespace and normalising absolute paths to their basename (the authors' machine paths cannot appear in our run). Blocks are aligned in order (longest common subsequence on command text). An unaligned expected block is `NOT_RUN`.
- **Output, headline ("token match").** Each output line is split on whitespace. Same token count per line, same number of lines, then token by token:
  - Non-numeric tokens: exact.
  - **Integers (no decimal point, no exponent): exact.** Observation counts, degrees of freedom, group sizes, years. Rule `.1` allowed ±1 on these, so `1000` matches `1001`. That passes a wrong N. Not allowed here.
  - Decimals: the actual token must be within **1 unit of the last printed digit of the expected token** (an expected `0.1234` accepts `0.1233`–`0.1235`) and must print the same number of decimals. Thousands separators ignored. Exponent forms compared by value.
  - A decimal that differs by exactly one unit is counted as `APPROX` and reported. A rate of `APPROX` above 5% of matched numeric tokens in a case is a flag for review, not a failure.
- **Output, strict ("layout match").** Same, with exact spacing after right-trimming. Reported beside the headline, not part of it. It catches table layout bugs the token rule cannot see.
- **Empty expected output** (`generate`, `replace`, `drop`, ...): matches if the command ran without an engine error **and the witness rule holds.**

### Witness rule (guards against silent no-ops)

A command with no output can be passed by an engine that does nothing. So: a silent command is credited only if the **next counted output-bearing block in the same recorded session of the authors' log** matches (.14.2). A session ends at a log header or footer block (section 1, last-statement point), so output from another session never witnesses it. The log does not always show where one do-file ends inside a session (a `do` call runs another file in the same session), so the search is per session, not per do-file. A silent command with no later output-bearing block in its session is credited if the engine ended without a stop and **that session** has at least one matching output-bearing block. The primary score uses this rule. The unwitnessed number (every silent command that ran without error is credited) is reported beside it, because the project's headline definition is "executes with output that matches".

## 3. Failure classes (each failed block gets exactly one)

| Class | Meaning |
|---|---|
| `AMBIGUOUS` | The output matches, but the scorer does not read the echo of this command, on either side (section 1, .13). No credit of any kind. |
| `UNSUPPORTED` | The engine said it does not support the command or option. Correct behaviour; scores no credit. |
| `NOT_RUN` | No aligned block in the actual transcript. Includes every block after the engine stopped. |
| `WRONG` | The engine ran the command with no error and printed output that does not match. These are the **known wrong results** the release rule counts. |
| `ERROR` | The engine raised an error the authors' log does not show. |
| `CRASH`/`TIMEOUT` | Engine process died or hit the time cap. Blocks after it are `NOT_RUN`. |

After the engine's first `UNSUPPORTED`, `ERROR` or `CRASH` in a do-file, **every later block of that do-file is `NOT_RUN`**, even if the engine continues. Continuing past an error means state is a guess. The one exception is the failing block itself: when the authors' log shows the same error at the same command, that block is compared instead of being marked `ERROR`, under the conditions below. The blocks after it are `NOT_RUN` all the same.

Whether the engine stopped is decided by its process status, and where it stopped is read from the transcript (.14.5). The engine's command line writes a stop line (`** ose: error|unsupported|crash: …`) as the transcript's last line exactly when it exits 1, 2 or 3, and never when it exits 0.

- **Exit 0:** the run ended cleanly. A last line that looks like a stop line is ordinary output, compared like any other.
- **Exit 1, 2 or 3:** the run stopped, as `ERROR`, `UNSUPPORTED` or `CRASH`. If the transcript's last non-blank line is a stop line, that line is the engine's record and is not compared (.14.6: the record is found by this position, never by its text; a line with the same text anywhere else is ordinary output and is compared). An `end of do-file` line directly before the record, in the same block, is the engine's footer and goes with it. The record names the failing command by where it sits: at the end of the last block's output, that block takes the stop; after a new log header, where section 1 assigns output to no block (a command that opened a log and then failed before the next echo), the last block takes the stop whatever its output before the header shows. With no stop line, the last block takes the stop all the same.
- **Any other status, or a timeout:** a process killed by a signal (a negative status), a status outside 0 to 3, or a run stopped by the time cap wrote no stop line. The run stopped as `CRASH`, the last block takes it, and no line is taken out. A timeout has no process status; the harness tells the scorer the run timed out and never stands in an exit code for it (.14.6).
- **No status:** when a transcript is scored without its process status, a stop-shaped last line is read as a stop, and the run is never taken to have ended cleanly. A transcript alone cannot separate a displayed string from a real stop, or a finished run from a killed one, so both readings can only withhold credit.

A block that takes an `UNSUPPORTED` or `CRASH` stop is never `MATCH`, whatever its output: a log made by Stata can show the same Stata error at the same command, but it never shows the engine's own unsupported or crash stop (.14.6).

A block that takes an `ERROR` stop is compared with the authors' block only when the stop record ends that block's own output. A stop held after a new log header stays `ERROR`. When it is compared, the rest of section 3 and section 1 still apply (.14.7):

- different output is `ERROR`;
- equal output is `MATCH` only when both echoes are read (section 1). If either echo is unread, equal output is `AMBIGUOUS`, which earns no credit.

The engine's failing command is the last statement in its transcript, and section 1 does not read a last statement. So today, error output equal to the authors' is `AMBIGUOUS` and never earns credit. It is counted, and it is never `ERROR`.

A run that stopped did not end cleanly, so the session-end fallback in section 2 credits nothing; it also credits nothing when there is no status.

## 4. What is reported

For every run: `rules` version, engine commit, set (`open` or `heldout`) and generation.

- Numerator and denominator in commands, packages and cases. Headline = witnessed matched commands / counted commands, pooled over cases (micro).
- Package-weighted mean (macro) beside it, and a package-level bootstrap interval (2,000 resamples, seed fixed in the rules) on the headline. Held-out sets of 30–100 packages need an interval to mean anything.
- Cases and packages that run end to end (all counted blocks match).
- Counts per failure class and the count of `WRONG` blocks.
- Strict layout score, unwitnessed score, `APPROX` count.
- Excluded-volatile counts.
- The largest package's share of the denominator.

## 5. Unsupported commands the engine must refuse

`shell`, `!`, `winexec`, `xshell`, and any command that runs another program must be refused with `UNSUPPORTED` and an engine error. The inputs are strangers' do-files; the engine is not allowed to run anything they name. Scored as `UNSUPPORTED`, not penalised beyond that.

## 6. Volatile output (excluded, counted, listed per package)

- **Clock and machine:** commands that print dates, times, elapsed time, memory, host or user names, working directory or paths (`display c(current_date)`, `$S_DATE`, `timer list`, `creturn list` fields on those, `pwd`, `query`-style dumps). Detected by a fixed, versioned pattern list in the scorer.
- **Random numbers.** The engine cannot be expected to reproduce another program's generator. Therefore:
  - Commands that consume the RNG are excluded: `runiform()`, `rnormal()`, `rbinomial()` and the other `r*()` functions, `set seed` followed by `bootstrap`, `bsample`, `simulate`, `sample`, `splitsample`, `permute`, and `jackknife` with random subsetting.
  - Later commands count normally. If they mismatch because the data came from the RNG, they are `WRONG` or `NOT_RUN`. That biases the score down and is the conservative direction.
  - Each package is flagged `rng=yes/no`. A **no-RNG score** (packages with `rng=no` only) is reported beside the headline, so readers can see how much RNG use costs.
- Version-dependent text (banner, `version` line, deprecation notices) is ignored.

## 7. Tolerance for the estimator era

When estimator output arrives, the numbers come from iterative optimisation. The rule stays the printed-digit rule: expected `0.1234` accepts `0.1233`–`0.1235`. No wider tolerance is added without a dated entry, a reason, and a count of how many blocks the change would flip on the **open** set.

## 8. Release wording and tempfile names (added in .3, 2026-11-25)

Reason: the open set shows the same block printed with different wording by different Stata releases (`# of obs.` vs `Number of obs`, `(note: variable ...)` vs `(variable ...)`) with every number equal, and tempfile names that differ by machine. The engine cannot know which release the author ran, and the do-file does not say (`version 11;` does not change display text).

**8.1 Tempfile names are machine paths.** In output lines, an absolute path whose last component is a Stata or engine tempfile name (`St<digits>.<digits>`, `ST_<word>.tmp`, `ose<word>.tmp`, `__<word>.tmp`, where `<word>` is one or more letters, digits or underscores) becomes `<TEMPFILE>` on both sides. Applies to headline **and** strict layout, as the volatile rule does. Text around the path is still compared. Other absolute paths in output stay exact; if they cost real blocks, that is a new dated entry with a count. A tempfile path also sets where a long save note wraps. Only in the output of a `save` command (abbreviations `sa`, `sav`, after `capture`, `quietly` or `noisily`, and only a plain echo (section 1): `/* note */ save x`, or a `save` continued after `/// text`, is not read and its notes are compared as printed), and only the two notes that the open logs show for a tempfile save, are lines joined: `(file <path> not found)` and `file <path> saved` with or without ` as .dta format`, where `<path>` is a tempfile path. A line that starts one of them is joined with the next one or two lines indented exactly four spaces, with a single space, only when the joined text is exactly one complete note. Both lengths are tried and the longer complete note wins, so a note split before `saved` and again before `as .dta format` is one note. Then the placeholder applies, on both sides (.6, narrowed in .7 and .8). Every other line stays as printed, including any output of any other command, even a line shaped like a save note.

**8.2 Wording table (headline only).** `harness/wording-table.tsv` (a snapshot of the table both scorers share) lists regex rewrites applied to every output line of both sides before the token comparison. Strict layout never uses it, so it still counts these lines as misses.
- An entry needs two open-list logs from different releases showing the same block with equal numbers (for an optional line: one log with it, one without). Entries come from the open list only, never from held-out misses.
- **Fixed-template lines (clarified in .4).** For a line that is a fixed template (only names and numbers vary, such as a coefficient-table title row), "the same block" means the same line template printed by the same Stata routine, even if the two logs ran different commands (`regress` in one, `reghdfe` in the other), provided the numeric tokens of the line are equal. The rest of the block is still compared exactly. An entry covers only the variant the open list witnesses.
- **Label-only entries (added in .12).** An entry may also rest on two open-list logs whose numbers differ, when all of these hold: it rewrites only a label of letters and spaces at the start of the line; everything after the label is left as printed and must match a lookahead that fixes the rest of the line's template; and the open harness test shows that changing any one number of a matched line still scores a miss. The numbers of such a line are the data's (a year range, a variable name), not the release's, so two packages can never print them equal.
- No entry may contain a digit or change the sequence of numeric tokens. What the open harness checks (`tests/unit/test_wording_table.py`): every entry's regex and replacement contain no literal digit (group references such as `\1` aside); every entry has a sample line in the test, written by us; the sample matches the entry; rewriting it leaves the sequence of numeric tokens unchanged; and so does rewriting each variant of the sample with a digit inserted at one position, wherever the entry still matches. A sample must hold numbers unless the entry is marked text-only: `merge-result-header` rewrites a line that never holds a number, so its sample has none, and the test checks that no variant with a digit matches it. A new entry without a sample fails the test. These are checks on samples, not a proof over all lines. Numbers are never normalised.
- Table version = the file hash, printed with the rules version in every run.
- The engine prints the newest wording the open set has witnessed. It is not asked to print several.

**8.3 What the table cannot do, and is not allowed to hide.** A held-out log from a release whose wording is not in the table scores `WRONG`. Every held-out run therefore also reports `wrong_blocks_numbers_equal`: `WRONG` blocks whose numeric tokens, in order, equal the expected ones after rewriting. That count is the visible cost of release wording. Wording seen only in held-out logs is never given to builders, so the table cannot be extended from held-out misses; only the count is shared. The held-out scorer computes this count; the open harness (`harness/logmatch.py`, `harness/run.py`) does not yet (change log, .3).

**8.4 Not allowed:** dropping or inserting lines (the `(file ... not found)` line stays exact until an optional-line entry has its evidence), case-folding the whole line, or any normalisation of digits.

## Known weaknesses of these rules (stated, not fixed)

- Top-level command counting makes a long loop worth one command. A package built on loops under-weights its real work.
- `APPROX` accepts a one-digit difference in the last printed place. For a value like `0.001` that is up to 100% relative error. The `APPROX` flag and the strict score exist for that.
- The witness rule credits a silent command on evidence that a later output is right. It does not prove the silent command was right.
- Without the engine's process status, the scorer cannot tell a displayed line shaped like a stop line from a real stop, or a finished run from a killed one (section 3, .14.5). It then withholds credit in both cases. The open harness always passes the status.
- The scorer compares displayed echoes, not do-file text (section 1, .14.1). A difference the display or the whitespace normalization hides, such as a tab against blanks inside a quoted string, is invisible to it.

## Lists used by both implementations (2026-11-24.2)

Kept here so the two scorers cannot drift. A change is a rules change.

- **Not counted (session settings):** `set more|rmsg|linesize|pagesize|scrollbufsize|trace|tracedepth|logtype`,
  `version`, `pause`, with or without `capture`/`quietly`, when the scorer reads the echo (section 1). Also
  comment-only blocks the echo proves are comments (section 1) and `log using|close|on|off` blocks the scorer reads.
  An unread echo of any of these is counted (section 1, *Not counted*).
- **Volatile, clock and machine:** `c(current_date)`, `c(current_time)`, `c(hostname)`, `c(username)`, `c(pwd)`,
  `c(memory)`, `c(processors*)`, `$S_DATE`, `$S_TIME`; commands `timer`, `pwd`, `query`, `creturn`, `memory`, `about`.
- **Volatile, random numbers:** the functions `runiform runiformint rnormal rbinomial rpoisson rbeta rchi2
  rexponential rgamma rhypergeometric rigaussian rlogistic rnbinomial rt rweibull rweibullph` anywhere in the
  command; the commands `bootstrap bs bsample simulate sample splitsample permute` in command position (start of
  the command after `capture`/`quietly`/`noisily`, or after a prefix colon). `if sample==1` is not RNG.
- **Bootstrap interval:** 2,000 package-level resamples, seed 20261124, 2.5% and 97.5% order statistics.

## Rulings when .2 was adopted (2026-11-24)

1. **Integers exact: accepted.** Rule `.1` let `1000` match `1001`, which passes a wrong N or degrees of
   freedom. The held-out scorer's authors measured the defect; `.2` fixes it.
2. **Witness rule as the headline: accepted.** The unwitnessed figure is reported beside it.
3. **Random-number exclusion: accepted**, with the excluded counts and the no-RNG score always printed next to the
   headline, in public too. The engine still has to run an excluded command: if it stops there, every later
   block is `NOT_RUN`, so an unsupported `bootstrap` still costs the rest of its do-file.
4. **An unrecognised command is `UNSUPPORTED`** (exit 2), whether it is a built-in the engine lacks or a
   user-written command. The engine cannot tell them apart and must not continue. `capture` does not turn an
   unsupported command into a return code.

## Change log

- 2026-11-24.14.7 (2026-11-25): the transcript the harness scores is the run's own, and the text on equal error
  output states its conditions. Reasons: the harness wrote each run's transcript to one kept path per case. A rerun
  that timed out before the engine opened its transcript was scored with the previous run's transcript, so rows
  could earn credit for commands that this run never ran. Now each run writes into a directory made for it alone. A
  transcript left by a previous run is removed before the engine starts, and a run with no transcript of its own is
  scored with none. Also, section 3 said that an `ERROR` block whose output equals the authors' is a match. The
  scorer also needs both echoes read, and the engine's failing command is always the unread last statement of its
  transcript, so today that block is `AMBIGUOUS` with no credit. The text now says so; the scorer is unchanged.
  Open set (21 cases): no row changes.
- 2026-11-24.14.6 (2026-11-25): the engine's stop record is found by its position, and a timeout reaches the scorer
  as a timeout. Reasons: under .14.5 the record was found by comparing text with the last block's output, so a
  command that printed the same line before opening a log, and then failed after the new header, lost the printed
  line instead and could score `AMBIGUOUS` or `MATCH` instead of `ERROR`. And the harness passed a timeout as exit 3,
  so the scorer could take an ordinary last line out as a record and lose the row's `CRASH`. Now the record is the
  transcript's last non-blank line, taken out at that position only; a timeout is passed as such and takes the
  `CRASH` with nothing taken out; and a block that takes an `UNSUPPORTED` or `CRASH` stop is never `MATCH`, which
  changes no transcript the engine writes today, since it prints its own message on both. Open set (21 cases): no
  row changes.
- 2026-11-24.14.5 (2026-11-25): whether the engine stopped is decided by its process status, and the transcript
  only says where. Reason: under .14.4 a process killed by a signal (negative status) or ending with any status
  other than 1, 2 or 3 left no stop line and no stop, so a silent row could earn the session-end fallback credit
  meant for a clean end. And on exit 0, a displayed string shaped like a stop line after a new log header was read
  as a stop. Now exit 0 never stops, 1 to 3 keep their meanings, any other status is `CRASH`, and with no status
  the fallback credits nothing. Open set (21 cases): no row changes.
- 2026-11-24.14.4 (2026-11-25): the engine's stop is read from the transcript's last line and from its exit code,
  not only from the last block's output. Reason: under .14.3 a command that opened a log and then failed before
  the next echo left its stop line in output that belongs to no block. The scorer looked for the stop only in the
  last block and knew only exit code 3 without it, so an error or an unsupported stop there could leave the failing
  row `MATCH` and let the session-end fallback treat the run as clean. Open set (21 cases): no row changes.
- 2026-11-24.14.3 (2026-11-25): output after a session boundary and before the next session's first echo belongs
  to no block. Reason: under .14.2 those lines joined the previous session's last block, so a log opened inside a
  loop could give that block output it never printed and change what its row, and the session-end fallback for an
  earlier silent command, saw. They are now left out, as lines before a log's first echo always were. Open set (21
  cases, one session each): no row changes.
- 2026-11-24.14.2 (2026-11-25): the witness rule stays in its recorded session; text corrections in sections 1 and
  the lists. Reason: .14.1 used a session boundary to decide whether an echo was read, but the witness search in
  section 2 still ran over the whole case, so the first output of a second session could witness a silent command
  of the first, and the end fallback looked for any matching output in the case. Both now look only inside the
  silent command's session. Text only: section 1 no longer says what the engine echoes (it does echo `log` lines),
  states that the one look past an echo is the last-statement point, and the not-counted list says "the scorer
  reads". Open set (21 cases, one session each): no row changes.
- 2026-11-24.14.1 (2026-11-25): rule 7 also stops at a session boundary; section 1 states what it measures.
  Reason: the scorer removed the log's header and footer blocks before looking for an echo after a statement, so in
  a log file with two recorded sessions the first echo of the second session counted as the next statement of the
  first, and the first session's last statement could be read as plain and earn credit. A header or footer block
  between an echo and the next one now makes the echo unread. Text only: section 1 said the scorer reads the
  command; it reads the displayed echo, which shows a tab as blanks, and section 2 merges runs of blanks, so it now
  says that a credited row means the displayed command and the output agree, not that the command text was
  byte-identical. The not-counted list now says that a `log` line or setting the scorer cannot read (`log close;`)
  is counted and `NOT_RUN`, as the .14 entry below records. Count on the open set (21 cases, rescored from the
  .14 run's transcripts; no engine change): 210/1,543 (unwitnessed 312, strict 208), 0 `WRONG`, 228 `AMBIGUOUS`,
  as under .14. No open log holds a second session, so no row changes.
- 2026-11-24.14 (2026-11-25): section 1 does not read an echo with a `;`, nor the last statement of a do-file.
  Reason: .13 let a closing `;` go and checked only that each way of joining an echo's lines gave the same kind of
  command. Two readings can be different commands of the same kind. Under `#delimit ;`, a long `local` on one line
  and the same text broken at the echo width give the same echo, and the second stores one more blank. `local x
  abc;` stores `abc;` in CR mode and `abc` in `;` mode, and a log can open after the directive. Either pair could
  earn credit. With no `;` an echo was not in `;` mode, so each `> ` is a wrap; that argument needs a next do-file
  line, so an echo with no next statement in the log is not read. The join check is kept as a guard that can only
  withhold credit. Count on the open set (21 cases, fresh transcripts): 338/1,541 under .13 becomes 210/1,543
  (unwitnessed 312, strict 208), 0 `WRONG`, 228 `AMBIGUOUS`. No row gains credit. The 128 rows that lose credit
  are all in the two logs of one package written in `;` mode; their output still matches. The 2 new rows are its
  `log close;` lines, which are no longer read as `log` lines. The last-statement rule changes no row: every open
  log ends with `log close`.
- 2026-11-24.13 (2026-11-25): section 1 reads an echo only when every reading of it agrees; the rest is counted and
  never credited. Reason: .9, .10 and .11 each worked out from the echo where the do-file's lines ended and which
  delimiter mode applied, and each was shown to read some echo wrongly in a way that changed the count or the credit
  (in .11: a comment on one side credited against a silent command on the other, and a do-file's last `///`
  comment counted). The echo does not carry that information, and a log can open after a `#delimit ;`, so the
  mode at its start is not known either. .13 removes the reading of line structure, width and mode. An echo is
  plain only when every reading in either mode gives the same command; a row earns credit only when both its echoes
  are plain. Count on the open set (21 cases, fresh transcripts): 523/1,523 under .11 becomes 338/1,541
  (unwitnessed 440), 0 `WRONG`, 100 `AMBIGUOUS`. No row gains credit. Of the 523 rows credited under .11, 338 keep
  it, 87 become `AMBIGUOUS` (mostly regressions continued with `///` and `esttab` lines) and 98 still match but
  lose witnessed credit because the next output-bearing block is now `AMBIGUOUS`. 14 blocks that .11 read as
  comments are counted (11 `AMBIGUOUS`, 3 `NOT_RUN`). Same version, engine: an empty continuation line is echoed as
  `> `, as logs print it; under .13 its echo is counted, and the old `>` showed as one `WRONG` row.
- 2026-11-24.12 (2026-11-25): 8.2 label-only entries. Reason: the open list shows the `xtset`/`tsset` summary in
  two releases (title-case labels in one package, lowercase in three), but its time line holds each data set's year
  range, so no two packages can print equal numbers there and the equal-numbers evidence test could never be met for
  it. A label-only entry now needs a lookahead that fixes the rest of the line and a test showing that a changed
  number still misses. No scorer code changes. Count on the open set (25 cases with the four declaration cases): 0 of
  the 1,529 rows of the 21 earlier cases change; with the three entries in the table the three older-release
  declarations score `MATCH` (headline) instead of `WRONG`, and the newer one stays a strict `MATCH`.
- 2026-11-24.11 (2026-11-25): section 1 uses only the command's own echo, and an ambiguous row earns no
  credit. Reason: .10 took the narrowest wrap width seen anywhere in the log. When the width changed, an earlier
  echo wrapped at another width was split at the wrong places, and a statement the engine ran and printed was read
  as a `*` comment and left the count, without a flag. .10 also let an ambiguous row reach `MATCH`: an empty `;`
  statement whose other reading was a command took headline and strict credit when the next display matched. Only
  the expected side's ambiguity was on the row. And .10 changed the delimiter mode on a `#delimit` it found after
  removing a comment, which the engine treats as an ordinary line and ignores. Now the width comes from the echo's
  own lines, and a reading that leaves `///` or `/*` open at its end is impossible. The mode changes only on a
  directive that starts its line. A commented directive, or a nested do-file after a `;` directive, makes the mode
  unknown and both modes are read. Ambiguity on either side gives class `AMBIGUOUS` with no credit. `#delimit`
  directives are no longer counted, like the other session settings, and a `log` line is not counted
  whatever its `capture`, `quietly` or `noisily` prefixes (.10 left out `log` and `capture log` only, and the
  held-out scorer read the text more widely). Count on the open set: 0 rows change, and no block is ambiguous. The
  same 1,529 rows keep their class, strict flag, exclusion and credit, both on the engine of this release (1,523
  commands, 523 matched, 0 `WRONG`) and on the current development engine (748 matched, 2 `WRONG`).
- 2026-11-25 text correction, no change of version or behaviour: section 8.1 said `<alnum>` where both
  implementations read letters, digits and underscores; engine temp names can contain `_`. Reported by the held-out
  scorer's owner on engine transcripts (one `save` row differed); the text now says `<word>`.
- 2026-11-24.10 (2026-11-25): section 1 reads each command as it runs, from the echo's line structure. Reason: .9
  decided where a physical line ends by whether the text before `> ` ended in `///`. A `///` followed by comment
  text (`/// a description`, then `save x` on the next line) and a line comment followed by a statement under
  `#delimit ;` were read as one wrapped comment, so an executed command and its output left the count. .9 also
  checked the `*` comment on the raw echo (`/* before */ * note` counted), counted an empty `;` statement, and
  put a blank where a same-line block comment had been (`s/* x */ave` was not a `save`). Now a new physical line
  is possible only after `///`, under `#delimit ;` or inside an open block comment, and the echoed line's length
  decides between a wrap and a new line; where it cannot, both readings are taken and a disagreement makes the
  block `echo_ambiguous` (counted, not excluded, not joined). Same version: the open harness no longer marks line
  boundaries with a character inside the text (.9 used U+001F and removed it from output, so `A<U+001F>B` matched
  `AB`). Count on the open set: 0 rows change (1,523 commands, 523 matched, 0 `WRONG`, the same 1,529 rows with
  the same class, strict flag, exclusion and credit as under .9); no open block is ambiguous.
- 2026-11-24.9 (2026-11-25): one comment-aware reading of each command (section 1) now decides what counts
  and what kind of command it is, for the denominator, the not-counted and volatile lists, and the 8.1 `save`
  condition. Reason: .8 used two readings. Its comment check stripped only the first `/* */` pair, so a nested
  comment (`/* a /* b */ c */`) or a block comment followed by `//` counted as a command; and its `save` check read
  the raw echo, so `/* note */ save x` was not a `save` and its wrapped note scored `WRONG` against an equivalent
  one-line note. Count on the open set: 0 rows change (1,523 commands, 523 matched, 0 `WRONG`, the same 1,529 rows
  with the same class, strict flag and exclusion as under .8); no open log has a comment before a `save`.
- 2026-11-24.8 (2026-11-25): 8.1 join limited to the output of a `save` command, and the longer of the two
  continuation lengths wins. Reason: under .7 a `display` that printed two lines shaped like a save note was joined
  and scored a strict match against a one-line transcript; and a note split before `saved` and before
  `as .dta format` was cut after the shorter complete note, so an equivalent note scored `WRONG`. Count on the open
  set: 0 blocks change; all 7 tempfile `save` notes are top-level `save` commands and keep their .7 result.
  Same version, an implementation fix with no rule change: the open harness now leaves lines that hold only
  `/* */` comments out of the count, as section 1 already said. Before this it counted them: on the open set,
  28 rows, 9 of them credited, so open scores labelled .5 to .7 overstate both counts by those rows (1,551 -> 1,523
  commands, 532 -> 523 matched). Section 1 now also says in words that a line with code next to a closed comment
  counts: 28 such open rows stay counted, 12 with code after a comment and 16 with code before one (count corrected
  on 2026-11-25 from "12"; the rows were always 28, only the text was wrong).
- 2026-11-24.7 (2026-11-25): 8.1 join narrowed to the two complete save notes. Reason: the .6 condition joined any
  four-space line after any line carrying a tempfile path, so a separate result printed after a path (for example by
  `display`) could be merged into it and a wrong transcript scored as a strict match. The three save blocks that .6
  was added for still match under .7.
- 2026-11-24.6 (2026-11-25): 8.1 joins the four-space continuation lines of a note that carries a tempfile path.
  Reason: in the open set the authors' tempfile notes wrap (`file … saved` / `as .dta format`, `(file … not` /
  `found)`) because their path is about 70 characters long; any other machine's path wraps elsewhere or not at all,
  so no engine could match these lines line by line. Count: 3 `WRONG` blocks in 2 open cases (HNPXO1 08 and 09) under
  .5, all tempfile `save`; 7 tempfile `save` notes in open logs are affected. The engine change that goes with it (the
  `as .dta format` suffix and the `not found` note) is a separate engine fix, not a rule.
- 2026-11-25 (no rule change, version stays .5): text corrections only. 8.2 now describes the wording-table test as
  it runs (inserted-digit variants, the text-only entry); 8.3 says which scorer reports `wrong_blocks_numbers_equal`;
  the .4 entry's table count is 94, the count in the cited logs. The table's evidence column and header were corrected
  the same way. Table SHA-256 `37892d2eb156102e49d70ebf8ffff6e0c388bd5dd7e166a7dfb83e840fbbd575`.
- 2026-11-24.5 (2026-11-25): wording-table entry `save-saved-as-dta` removed. Reason: on re-reading the evidence,
  `file X saved as .dta format` appears only when the saved name has no `.dta` extension (a tempfile), so the suffix
  follows the file extension, not the Stata release; the entry hid a real engine difference. An engine that prints
  `saved` for a name without `.dta` is now a miss. The table's header was rewritten for publication. Table SHA-256
  `93e4aeba7256dc3a40b6db8813d11b8bc451f38e9957ec6cd723cdd43e93ca23`.
- 2026-11-24.4 (2026-11-25): wording-table entry `coef-table-titles-t` and the fixed-template clarification in 8.2.
  Evidence: the old title row (`Coef.   Std. Err. ... [95% Conf. Interval]`, 218 tables in the open-list packages
  3EDO2Y and 27102) against the new one (`Coefficient  std. err. ... [95% conf. interval]`, 94 tables in the 12
  HNPXO1 analysis logs, `02_table2_baseline` to `13_figure4_parallel_trends`; an earlier text said 282, which no
  inventory we hold supports),
  equal in every number. That both commands print the title through the same routine is an inference, not tested.
- 2026-11-24.3 (2026-11-25): section 8 (tempfile placeholder, wording table, numbers-equal count). The open harness
  reads the table and prints its hash. Not ported yet: the `wrong_blocks_numbers_equal` count (8.3). Effect on the
  open set when adopted: R7RYIV's 4 wording misses became matches. Session width: the open harness passes
  `--linesize` read off the expected log.
- 2026-11-24.2: integers exact; decimals within one printed unit with the same number of decimals, `APPROX`
  counted; witness rule; failure classes; stop rule; clock and RNG exclusions; transcript as the record; package
  bootstrap interval. Reason: the `.1` integer tolerance passed wrong counts, and `.1` could not tell a wrong
  number from a command that never ran. HNPXO1 `15_figure_a1` scores 6/6 under both versions (strict layout also 6/6).
- 2026-11-24.1: first version.
