# Open stats engine in the browser

## Run the generated example

From the repository root, use Python 3.11 or newer and a desktop browser with
JavaScript enabled. If the build cache is empty, the build downloads the pinned
Pyodide runtime and wheels from jsDelivr and the optional author scripts and
license from Dataverse.

```sh
python3 web/build.py
python3 web/serve.py
```

Keep the server running and open [the workspace on this machine](http://127.0.0.1:8560/).
Leave **100 observations** selected and click **Run do-file** when it becomes
available. The example generates its own data.

Look for **Run complete** in **Run log**. Under `summarize x`, expect this row.

~~~text
Variable |   Obs   Mean   Std. dev.   Min   Max
       x |   100    5.5    3.056703     0    11
~~~

The `x.svg` histogram appears below the log.

Choose **Blank do-file** to start with your own code. To use an attached dataset,
refer to its filename in the code.

## Optional author replication

Use both flags to prepare and serve a personal replication copy of the author
dataset on loopback.

```sh
python3 web/build.py --with-replication-data
python3 web/serve.py --with-replication-data
```

Open the same workspace and choose **Lake Tai · Figure A1** for Qing Li’s
original do-file and summary, or try the longer **Lake Tai · Table 2** example.
The replication data stays in the ignored `web/.replication/` directory and is
served only by the opted-in loopback process. The authors’ license limits
`final.dta` to replication and prohibits redistribution.
[Dataverse deposit](https://doi.org/10.7910/DVN/HNPXO1) · [Author’s license, section 4](https://dataverse.harvard.edu/api/access/datafile/14443860)

The worker keeps attached files, transcripts and exports in memory. **Stop run** restarts the worker and keeps the editor and selected files. The preview displays SVG exports. The Figure A1 author script exports PDF, so that run is visible in the log.

[Measurements](MEASUREMENTS.md) · [Desktop histogram](evidence/success-1440.png) · [Mobile histogram](evidence/success-390.png)
