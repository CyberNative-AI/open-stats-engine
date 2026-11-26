"""Measure fresh signed-out Chrome and Firefox sessions on Linux loopback."""

import argparse
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
from statistics import median
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread

import psutil
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support.ui import Select, WebDriverWait

from serve import BUILD, REPLICATION_DATA, WorkspaceHandler

PSS_INTERVAL = 0.05


class MeasuredHandler(WorkspaceHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BUILD), research=True, **kwargs)

    def copyfile(self, source, output):
        super().copyfile(source, output)
        self.server.payloads.append((self.path, os.fstat(source.fileno()).st_size))

    def log_message(self, *args):
        pass


class MemorySampler:
    def __init__(self, process):
        self.parent = psutil.Process(process)
        self.stop = Event()
        self.peak = 0
        self.thread = Thread(target=self._sample)
        self.thread.start()

    def _sample(self):
        while not self.stop.is_set():
            self.peak = max(self.peak, self.current())
            self.stop.wait(PSS_INTERVAL)

    def current(self):
        total = 0
        for child in self.parent.children(recursive=True):
            try:
                total += child.memory_full_info().pss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total

    def close(self):
        self.stop.set()
        self.thread.join()


def open_browser(name, binary, driver_path, config):
    env = {**os.environ, "TMPDIR": "/tmp", "XDG_CONFIG_HOME": config}
    if name == "chrome":
        options = webdriver.ChromeOptions()
        options.binary_location = binary
        for arg in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"):
            options.add_argument(arg)
        return webdriver.Chrome(options=options, service=ChromeService(driver_path, env=env))
    options = webdriver.FirefoxOptions()
    options.binary_location = binary
    options.add_argument("-headless")
    return webdriver.Firefox(options=options, service=FirefoxService(driver_path, env=env))


def state(browser):
    return browser.find_element(By.ID, "run-state").get_attribute("data-state")


def run(browser, expected):
    browser.find_element(By.ID, "run").click()
    WebDriverWait(browser, 30, poll_frequency=0.05).until(
        lambda driver: driver.execute_script(
            "const last = n => performance.getEntriesByName(n).at(-1)?.startTime; "
            "return last('run-rendered') >= last('run-start');",
        ),
    )
    actual = state(browser)
    assert actual == expected, (actual, browser.find_element(By.ID, "run-state").text)
    return browser.execute_script("""
        const last = n => performance.getEntriesByName(n).at(-1).startTime;
        return last('run-rendered') - last('run-start');
    """)


def measure(browser, server, author_checks):
    sampler = MemorySampler(browser.service.process.pid)
    baseline = sampler.current()
    payload_start = len(server.payloads)
    try:
        browser.get(f"http://127.0.0.1:{server.server_port}/")
        WebDriverWait(browser, 32, poll_frequency=0.05).until(
            lambda driver: state(driver) in ("ready", "crash"),
        )
        if state(browser) != "ready":
            raise RuntimeError(browser.find_element(By.ID, "run-state").text)
        cold_ms = browser.execute_script("return performance.getEntriesByName('engine-ready')[0].startTime;")
        if cold_ms > 30_000:
            raise RuntimeError(f"Cold start exceeded 30 s ({cold_ms:.1f} ms)")
        startup = server.payloads[payload_start:]
        warm = [run(browser, "success") for _ in range(5)]
        assert browser.execute_script(
            "return document.querySelector('#plots img')?.naturalWidth > 0;",
        ), "SVG did not decode"
        result = {
            "cold_ms": round(cold_ms, 2),
            "first_load_body_bytes": sum(size for _, size in startup),
            "startup_requests": [name for name, _ in startup],
            "warm_ms": [round(ms, 2) for ms in warm],
            "baseline_pss_bytes": baseline,
            "peak_pss_bytes": sampler.peak,
        }
    finally:
        sampler.close()

    if author_checks:
        from logmatch import match_logs, summarize
        run_wait = WebDriverWait(browser, 10, poll_frequency=0.05)
        chooser = Select(browser.find_element(By.ID, "example"))
        chooser.select_by_value("figure")
        run_wait.until(lambda driver: driver.find_element(By.ID, "run").is_enabled())
        run(browser, "success")
        published = author_checks.read_text(encoding="utf-8")
        actual = browser.find_element(By.ID, "log").get_attribute("textContent")
        score = summarize(match_logs(published, actual, exit_code=0))
        result["figure_a1_match"] = [score["matched"], score["commands"]]
        assert result["figure_a1_match"] == [6, 6], score
        chooser.select_by_value("baseline")
        run_wait.until(lambda driver: driver.find_element(By.ID, "run").is_enabled())
        run(browser, "unsupported")
        last = browser.find_element(By.ID, "log").get_attribute("textContent").strip().splitlines()[-1]
        result["table_2_last_line"] = last
        assert last == "** ose: unsupported: reghdfe", last
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", default="/usr/bin/google-chrome")
    parser.add_argument("--chromedriver", required=True)
    parser.add_argument("--firefox", default="/usr/bin/firefox")
    parser.add_argument("--geckodriver", required=True)
    parser.add_argument("--author-log", type=Path, help="compare Figure A1 with the source log and check Table 2")
    parser.add_argument("--sessions", type=int, default=3)
    args = parser.parse_args()
    if args.sessions < 1 or (args.author_log and not REPLICATION_DATA.is_file()):
        parser.error("Use at least one session and prepare replication data for author checks.")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))

    with ThreadingHTTPServer(("127.0.0.1", 0), MeasuredHandler) as server:
        server.payloads = []
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        output = {}
        try:
            for name, binary, driver_path in (
                ("chrome", args.chrome, args.chromedriver),
                ("firefox", args.firefox, args.geckodriver),
            ):
                attempts = []
                for attempt in range(args.sessions):
                    with TemporaryDirectory(prefix="ose-browser-", dir="/tmp") as config:
                        with open_browser(name, binary, driver_path, config) as browser:
                            version = browser.capabilities["browserVersion"]
                            attempts.append(measure(browser, server, args.author_log if attempt == 0 else None))
                    print(f"{name} sample {attempt + 1}: {attempts[-1]['cold_ms']} ms", file=sys.stderr)
                output[name] = {"version": version, "attempts": attempts, "median_warm_ms": median(
                    ms for attempt in attempts for ms in attempt["warm_ms"]
                )}
        finally:
            server.shutdown()
            thread.join()
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
