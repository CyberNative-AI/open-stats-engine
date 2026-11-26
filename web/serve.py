"""Serve the prepared browser spike on this machine's loopback interface."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from build import BUILD, REPLICATION_DATA

CSP = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
    "font-src 'self'; img-src 'self' blob:; worker-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class WorkspaceHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, research=False, **kwargs):
        self.research = research
        super().__init__(*args, **kwargs)

    def translate_path(self, path):
        if self.research and urlsplit(path).path == "/examples/final.dta":
            return str(REPLICATION_DATA)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_head(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.send_error(403)
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8560)
    parser.add_argument("--with-replication-data", action="store_true",
                        help="serve the locally fetched data for personal replication")
    args = parser.parse_args()
    if not (BUILD / "ose.zip").is_file():
        parser.error("Run python3 web/build.py first.")
    if args.with_replication_data and not REPLICATION_DATA.is_file():
        parser.error("Run python3 web/build.py --with-replication-data first.")
    handler = partial(WorkspaceHandler, directory=str(BUILD), research=args.with_replication_data)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Open http://127.0.0.1:{server.server_port}/", flush=True)
        server.serve_forever()
