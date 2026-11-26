const get = id => document.getElementById(id);
const editor = get("dofile");
const picker = get("dataset");
const drop = get("drop");
const example = get("example");
const runButton = get("run");
const stopButton = get("stop");
const log = get("log");
const logHint = get("log-hint");
const plots = get("plots");
const downloads = get("downloads");
const synthetic = editor.defaultValue;
const startupLimitMs = 120_000;

const examples = {
  figure: {
    file: "figure-a1.do",
    note: "Qing Li’s Figure A1 measures firms’ distance from city borders. The original do-file exports PDF, and the log shows the summary.",
  },
  baseline: {
    file: "table-2.do",
    note: "Qing Li’s baseline regressions. Run it to see how far the engine gets and the command where it stops.",
  },
};

let worker;
let ready = false;
let running = false;
let loadingExample = false;
let activeExample = "histogram";
let selection = 0;
let timer;
let outputUrls = [];
const attachments = new Map();
let pending = null;
let shown = null;

// Attached files are compared by content, not by name, size or date: two different files can share all three.
const fileHashes = new WeakMap();
let unreadable = 0;

async function hashBytes(buffer) {
  const sum = new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
  return Array.from(sum, byte => byte.toString(16).padStart(2, "0")).join("");
}

async function learnHash(file) {
  try {
    fileHashes.set(file, await hashBytes(await file.arrayBuffer()));
  } catch {
    // An unreadable file never matches, so the output stays marked as earlier.
    fileHashes.set(file, `unreadable-${unreadable++}`);
  }
  markStale();
}

// Attached files by name, in name order, so the order they were chosen in never matters. A hash of undefined is not read yet.
function attachedNow() {
  return [...attachments].map(([name, file]) => [name, fileHashes.get(file)]).sort((a, b) => (a[0] < b[0] ? -1 : 1));
}

// What the engine is given: do-file text, example kind, attached files by name and content.
function currentInputs() {
  return { dofile: editor.value, author: Boolean(examples[activeExample]), files: attachedNow() };
}

// "same", "changed", or "checking" while a file the comparison needs has not been read yet.
function compareFiles(before, now) {
  if (before.length !== now.length || before.some(([name], index) => name !== now[index][0])) return "changed";
  let checking = false;
  for (const [index, [, hash]] of before.entries()) {
    const other = now[index][1];
    if (other === undefined) checking = true;
    else if (other !== hash) return "changed";
  }
  return checking ? "checking" : "same";
}

// The output stays on screen, but it says so when the inputs beside it are no longer the ones that made it.
function markStale() {
  if (!shown || !worker) return;
  const now = currentInputs();
  const changed = [];
  if (now.dofile !== shown.inputs.dofile || now.author !== shown.inputs.author) changed.push("do-file");
  const files = compareFiles(shown.inputs.files, now.files);
  if (files === "changed") changed.push("attached files");
  const checking = files === "checking" && !changed.length;
  const figures = [...plots.querySelectorAll("figure")];
  for (const figure of figures) {
    const label = figure.querySelector(".previous");
    label.hidden = !changed.length;
    for (const link of figure.querySelectorAll("a")) {
      if (changed.length) link.setAttribute("aria-describedby", label.id);
      else link.removeAttribute("aria-describedby");
    }
  }
  if (!changed.length && !checking) {
    tell(...shown.state);
    return;
  }
  const [title, note] = checking
    ? ["Checking attached files", "The attached files are being compared with the ones this run used. The results below stay as they were."]
    : ["Showing the previous run",
      `The ${changed.join(" and ")} changed after this run started, so the results below come from the earlier version. ` +
      "Run the do-file again to update them."];
  if (shown.state[0] === "success") {
    tell(checking ? "checking" : "stale", title, note);
  } else {
    tell(...shown.state);
    get("state-previous").textContent = `${title}. ${note}`;
    get("state-previous").hidden = false;
  }
}

function settle(inputs, ...state) {
  shown = { inputs, state };
  tell(...state);
  markStale();
}

function refreshRunButton() {
  runButton.hidden = running;
  stopButton.hidden = !running;
  runButton.disabled = !ready || loadingExample || !editor.value.trim();
  runButton.textContent = !ready && worker ? "Loading engine…" : "Run do-file";
  get("startup-note").hidden = ready || !worker;
}

function tell(state, title, detail = "") {
  get("run-state").dataset.state = state;
  get("state-title").textContent = title;
  get("state-detail").textContent = detail;
  get("state-previous").hidden = true;
}

function clearOutput() {
  shown = null;
  for (const url of outputUrls) URL.revokeObjectURL(url);
  outputUrls = [];
  plots.replaceChildren();
  plots.hidden = true;
  downloads.replaceChildren();
  downloads.hidden = true;
  log.textContent = "";
  log.hidden = true;
  logHint.hidden = true;
  get("view-log").hidden = true;
  get("timing").hidden = true;
}

function closeWorker() {
  clearTimeout(timer);
  worker?.terminate();
  worker = null;
  ready = false;
  running = false;
  refreshRunButton();
}

function startupError(message, detail = "Try starting it again.") {
  console.error(message);
  closeWorker();
  tell("crash", "The browser engine couldn’t start", detail);
  get("retry").hidden = false;
}

function start() {
  get("retry").hidden = true;
  tell("loading", "Loading Python and SciPy", "You can edit the do-file while the engine starts.");
  let current;
  try {
    current = new Worker("worker.js");
  } catch (error) {
    startupError(error.message);
    return;
  }
  worker = current;
  refreshRunButton();
  current.onmessage = event => {
    if (current === worker) showMessage(event.data, current);
  };
  current.onerror = event => {
    if (current === worker) startupError(event.message);
  };
  timer = setTimeout(() => {
    startupError("Engine startup exceeded two minutes.",
      "The engine took more than two minutes to load. Check your connection and try again.");
  }, startupLimitMs);
}

function updateLogHint() {
  logHint.hidden = log.hidden || log.scrollWidth <= log.clientWidth;
  if (logHint.hidden) log.removeAttribute("aria-describedby");
  else log.setAttribute("aria-describedby", logHint.id);
}

async function showMessage(message, current) {
  if (message.type === "ready") {
    clearTimeout(timer);
    ready = true;
    tell("ready", "Ready to run", "Run the example or paste your own do-file.");
    refreshRunButton();
    performance.mark("engine-ready");
    return;
  }
  if (message.type === "startup-error") {
    startupError(message.message);
    return;
  }
  if (message.type === "result") {
    log.textContent = message.log;
    log.hidden = false;
    updateLogHint();
    const status = message.log.trimEnd().split("\n").at(-1)?.match(/^\*\* ose: (unsupported|error|crash): (.*)$/);
    if (message.code === 0) {
      await showPlots(message.graphs, pending);
      if (current !== worker) return;
      showDownloads(message.csvs);
      settle(pending.inputs, "success", "Run complete");
    } else if (status?.[1] === "unsupported") {
      settle(pending.inputs, "unsupported", `This engine doesn’t support ${status[2]} yet`,
        "The run stopped here. The log shows what ran before the stop. Try the 100 observations example for a complete run.");
    } else {
      const state = status?.[1] || "crash";
      const title = state === "error" ? "The do-file stopped with an error" : "The engine hit an internal error";
      settle(pending.inputs, state, title, status?.[2]);
    }
    log.scrollTop = message.code === 0 ? 0 : log.scrollHeight;
    log.scrollLeft = 0;
    get("view-log").hidden = false;
    const timing = get("timing");
    timing.textContent = `${Math.round(message.engineMs)} ms compute`;
    timing.hidden = false;
  } else if (message.type === "data-error") {
    tell("error", "The example data couldn’t be read",
      "Try again or load 100 observations, which needs no data file.");
  } else {
    console.error(message.message);
    tell("crash", "The engine hit an internal error", "Try running the do-file again.");
  }
  running = false;
  refreshRunButton();
  if (document.activeElement === document.body || document.activeElement === stopButton) {
    runButton.focus({ preventScroll: true });
  }
  performance.mark("run-rendered");
}

async function showPlots(graphs, run) {
  const images = [];
  for (const [name, svg] of graphs) {
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    outputUrls.push(url);
    const figure = document.createElement("figure");
    const caption = document.createElement("figcaption");
    // The text alternative describes the fixed example's output only, so it goes with the completed run's own script.
    const builtIn = name === "x.svg" && run.inputs.dofile === synthetic;
    const filename = document.createElement("span");
    filename.textContent = name;
    const previous = document.createElement("span");
    previous.className = "previous";
    previous.id = `previous-${plots.children.length}`;
    const dot = document.createElement("span");
    dot.setAttribute("aria-hidden", "true");
    dot.textContent = " · ";
    previous.append(dot, "previous run");
    previous.hidden = true;
    const heading = document.createElement("span");
    heading.className = "caption-name";
    heading.append(filename, previous);
    const download = document.createElement("a");
    download.href = url;
    download.download = name.split("/").at(-1);
    download.textContent = "Download SVG";
    download.setAttribute("aria-label", `Download SVG: ${name}`);
    caption.append(heading, download);
    const img = document.createElement("img");
    img.alt = builtIn
      ? "Frequency histogram of x for the 100 observations in the example. Read the text alternative for every bin and count."
      : `Graph exported as ${name}.`;
    img.src = url;
    figure.append(caption, img);
    if (builtIn) {
      const links = document.createElement("p");
      links.className = "plot-links";
      const read = document.createElement("a");
      read.href = "x-histogram-preview.html";
      read.target = "_blank";
      read.rel = "noopener";
      read.textContent = "Read text alternative (new tab)";
      const companion = document.createElement("a");
      companion.href = "x-histogram.html";
      companion.download = "x-histogram.html";
      companion.textContent = "Download text alternative (HTML)";
      const keep = document.createElement("span");
      keep.textContent = "Share both files together.";
      links.append(read, companion, keep);
      figure.append(links);
    }
    plots.append(figure);
    images.push(img.decode());
  }
  plots.hidden = images.length === 0;
  await Promise.allSettled(images);
}

function showDownloads(csvs) {
  for (const [name, bytes] of csvs) {
    const url = URL.createObjectURL(new Blob([bytes], { type: "text/csv" }));
    outputUrls.push(url);
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = url;
    link.download = name.split("/").at(-1);
    const filename = document.createElement("span");
    filename.className = "filename";
    filename.textContent = name;
    link.append("Download ", filename);
    item.append(link);
    downloads.append(item);
  }
  downloads.hidden = csvs.length === 0;
}

async function loadExample() {
  const choice = example.value;
  const request = ++selection;
  loadingExample = true;
  editor.readOnly = true;
  refreshRunButton();
  const source = examples[choice];
  get("file-message").textContent = "";
  try {
    let dofile = choice === "own" ? "" : synthetic;
    if (source) {
      const response = await fetch(`examples/${source.file}`);
      if (!response.ok) throw new Error("Example script unavailable.");
      dofile = await response.text();
    }
    if (request !== selection) return;
    editor.value = dofile;
    activeExample = choice;
    markStale();
    get("source").hidden = !source;
    get("source-note").textContent = source?.note || "";
  } catch {
    if (request !== selection) return;
    example.value = activeExample;
    get("file-message").textContent = "The example couldn’t load. Try choosing it again.";
  } finally {
    if (request === selection) {
      loadingExample = false;
      editor.readOnly = false;
      refreshRunButton();
    }
  }
}

function renderAttachments() {
  const list = get("attachments");
  list.replaceChildren();
  list.hidden = attachments.size === 0;
  for (const [name] of attachments) {
    const item = document.createElement("li");
    const filename = document.createElement("span");
    filename.className = "filename";
    filename.textContent = name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${name}`);
    remove.onclick = () => {
      attachments.delete(name);
      markStale();
      get("file-message").textContent = `Removed ${name}.`;
      renderAttachments();
      (list.querySelector("button") || picker).focus();
    };
    item.append(filename, remove);
    list.append(item);
  }
}

function addFiles(files) {
  let refused = false;
  for (const file of files) {
    if (!file.name.toLowerCase().endsWith(".dta")) {
      refused = true;
    } else {
      attachments.set(file.name, file);
      learnHash(file);
    }
  }
  renderAttachments();
  markStale();
  get("file-message").textContent = refused ? "Choose files with a .dta extension." : "";
}

async function run() {
  if (runButton.disabled || running) return;
  const retainFocus = document.activeElement === runButton;
  running = true;
  refreshRunButton();
  if (retainFocus) stopButton.focus();
  clearOutput();
  tell("running", "Running the do-file", "The log will appear here when the run ends.");
  performance.mark("run-start");
  const current = worker;
  const dofile = editor.value;
  const authorExample = Boolean(examples[activeExample]);
  const entries = [...attachments];
  try {
    const files = await Promise.all(
      entries.map(async ([name, file]) => [name, await file.arrayBuffer()]),
    );
    const hashes = await Promise.all(files.map(([, buffer]) => hashBytes(buffer)));
    if (current === worker) {
      pending = {
        inputs: {
          dofile,
          author: authorExample,
          files: files.map(([name], index) => [name, hashes[index]]).sort((a, b) => (a[0] < b[0] ? -1 : 1)),
        },
      };
      current.postMessage({ dofile, files, authorExample }, files.map(([, buffer]) => buffer));
    }
  } catch {
    if (current === worker) {
      running = false;
      refreshRunButton();
      tell("error", "An attached file couldn’t be read", "Remove the file, attach it again, and run the do-file.");
    }
  }
}

example.addEventListener("change", loadExample);
new ResizeObserver(updateLogHint).observe(log);
editor.addEventListener("input", () => {
  refreshRunButton();
  markStale();
});
runButton.addEventListener("click", run);
stopButton.addEventListener("click", () => {
  closeWorker();
  clearOutput();
  start();
  tell("loading", "Run stopped", "The engine is restarting. Your do-file and attached files are still here.");
});
get("retry").addEventListener("click", () => {
  clearOutput();
  start();
});
get("view-log").addEventListener("click", () => get("result-title").focus({ preventScroll: true }));
picker.addEventListener("change", () => {
  addFiles(picker.files);
  picker.value = "";
});
for (const event of ["dragenter", "dragover"]) {
  drop.addEventListener(event, drag => {
    drag.preventDefault();
    drop.dataset.drag = "";
  });
}
drop.addEventListener("dragleave", event => {
  if (!drop.contains(event.relatedTarget)) delete drop.dataset.drag;
});
drop.addEventListener("drop", event => {
  event.preventDefault();
  delete drop.dataset.drag;
  addFiles(event.dataTransfer.files);
});
start();
