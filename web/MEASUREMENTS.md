# Pyodide browser spike measurements

**Go for the desktop browser path.** SciPy loaded and evaluated a function in all six fresh browser sessions. The slowest loopback start was **7.47 s**, below the brief’s 30 s stop rule. The initial body was **30.20 MiB** in both browsers. Firefox’s **1,515 MiB** sampled peak makes physical-phone performance an open question.

| Browser | First-load body | Cold navigation to ready, median (range) | Warm run, median (range) | Sampled peak memory |
| --- | ---: | ---: | ---: | ---: |
| Chrome 157.0.8103.78 | 31,670,326 bytes | 5.48 s (5.36–5.56 s) | 10.6 ms (6.8–35.5 ms) | 612 MiB PSS, up to +354 MiB over idle |
| Firefox 158.0.1 | 31,669,403 bytes | 7.15 s (6.93–7.47 s) | 7.0 ms (7.0–16.0 ms) | 1,515 MiB PSS, up to +1,132 MiB over idle |

Measured November 24, 2026 Pacific time on Ubuntu 26.04.1 LTS, AMD Ryzen 7 3700X, with headless browser binaries and fresh signed-out profiles. Three sessions per browser, five runs of the 100-observation example per session. [Raw timing, asset and memory samples](evidence/benchmark.json)

## What each number includes

- **First-load body** sums completed loopback HTTP response bodies by ready. Cache was disabled and the server sent the files without HTTP compression. It excludes headers and the optional on-demand HNPXO1 data (25,557,784 bytes). Chrome requested the 923-byte mark twice. SciPy’s wheel accounts for 16,426,457 bytes of the startup body.
- **Cold** runs from the navigation time origin until the worker loads Pyodide 0.29.4, imports NumPy 2.2.5, exercises SciPy 1.14.1 and imports the engine. The page then enables Run. [Pyodide worker documentation](https://pyodide.org/en/0.29.4/usage/webworker.html)
- **Warm** runs from the button handler to the log update and successful SVG decode in the active session. The example uses `set obs`, `generate`, `replace`, both `summarize` forms, `histogram` and `graph export x.svg`.
- **Peak memory** is the largest sum of Linux proportional set size (PSS) for the browser process tree across each timed session. The sampler targets 50 ms intervals and includes browser overhead and startup through the last SVG decode. The idle comparison uses the same session before navigation. PSS includes Wasm and native allocations. Author-example checks ran after this sample window.
- **Coverage** includes full-browser desktop timing on loopback. Physical-phone timing and a remote network test were **NOT RUN**. At 30.20 MiB, the startup payload alone takes about 25 s over a steady 10 Mbit/s link before HTTP overhead and initialization. The browser spike is not published yet.

## Functional evidence

- HNPXO1 Figure A1 matched **6/6** scored commands against the author’s log in Chrome and Firefox. The original do-file ran with the pinned dataset and writes a PDF. The browser shows the transcript. Its screenshot shows the authors' script and output, so it is not published.
- HNPXO1 Table 2 stopped at `reghdfe` in both browsers. The panel names the unsupported command, shows the stop in the transcript, and points back to the working example. Those screenshots also show the authors' script, so they are not published.
- The synthetic case ran to completion and displayed its SVG histogram. [Desktop](evidence/success-1440.png) · [Phone-width](evidence/success-390.png)
- Chrome at 390 × 844 and 1440 × 900 passed the layout checks and axe scans for ready, success and unsupported. Controls were at least 48 px tall, and wide transcript lines scroll within the log. Keyboard focus, file-picker and drop input, removal, a missing-file error, a stopped run and startup retry all worked. The rendered phone view keeps the result below the editor, with a View run log link next to the inputs. The exported SVG has small axis text at phone width.
- The Object Atlas kit check passed. The unchanged native unit suite passed **33/33**, and the native open harness matched **6/6** scored commands.

## Re-run

Prepare the workspace as described in the [local setup](README.md). The benchmark uses Python with `selenium` and `psutil`, plus local ChromeDriver and GeckoDriver binaries. Give `--firefox` the real Firefox binary on a Snap installation.

```sh
python3 web/benchmark.py \
  --chromedriver /path/to/chromedriver \
  --firefox /path/to/firefox \
  --geckodriver /path/to/geckodriver \
  --author-log /path/to/author-figure-a1.log
```

The optional comparison uses Dataverse file 14443947, pinned in the [open case manifest](../tests/cases/open/dv-HNPXO1-15_figure_a1.json).
