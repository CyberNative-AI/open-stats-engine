/* The only network reads here are static assets on the same loopback origin. */
let py;
let runWithOutputs;
let exampleData;

async function readAsset(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not read ${path} (HTTP ${response.status}).`);
  return response;
}

async function start() {
  try {
    importScripts("pyodide/pyodide.js");
    py = await loadPyodide({ indexURL: "pyodide/" });
    await py.loadPackage(["numpy", "scipy"]);
    py.unpackArchive(await (await readAsset("ose.zip")).arrayBuffer(), "zip");
    py.runPython("import numpy, scipy\nfrom scipy.special import ndtr\nassert ndtr(0.0) == 0.5");
    runWithOutputs = py.runPython("from ose.web import run_with_outputs\nrun_with_outputs");
    postMessage({ type: "ready" });
  } catch (error) {
    postMessage({ type: "startup-error", message: error.message });
  }
}

async function run({ dofile, files, authorExample }) {
  let dirs = [];
  if (authorExample) {
    try {
      exampleData ??= await Promise.all([
        readAsset("examples/final.dta").then(response => response.arrayBuffer()),
        readAsset("examples/workspace.json").then(response => response.json()),
      ]);
      const [data, workspace] = exampleData;
      files.unshift([workspace.path, data]);
      dirs = workspace.dirs;
    } catch {
      postMessage({ type: "data-error" });
      return;
    }
  }

  const startTime = performance.now();
  const pyFiles = py.toPy(new Map(files.map(([name, data]) => [name, new Uint8Array(data)])));
  const pyDirs = py.toPy(dirs);
  try {
    const result = runWithOutputs(dofile, pyFiles, pyDirs);
    try {
      const [log, graphs, csvs, code] = result.toJs();
      postMessage({ type: "result", log, graphs, csvs, code, engineMs: performance.now() - startTime });
    } finally {
      result.destroy();
    }
  } finally {
    pyFiles.destroy();
    pyDirs.destroy();
  }
}

self.onmessage = async ({ data }) => {
  try {
    await run(data);
  } catch (error) {
    postMessage({ type: "run-error", message: error.message });
  }
};
start();
