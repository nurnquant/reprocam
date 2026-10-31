"""Serve the Lumen & Loom practice store on http://localhost:5173.

Run from the reprocam folder:  python scripts/serve_store.py [port]
Buggy build by default; open any page with ?fixed=1 for the fixed build (?fixed=0 to go back).
"""
import os
import socket
import sys
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

STORE_DIR = os.path.join(os.path.dirname(__file__), "..", "store")
DEFAULT_PORT = 5173


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def make_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    handler = partial(NoCacheHandler, directory=os.path.abspath(STORE_DIR))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@contextmanager
def store_running(app_url: str):
    """Serve the store for the duration, unless app_url is remote or something already listens."""
    url = urlparse(app_url)
    port = url.port or 80
    if url.hostname not in ("localhost", "127.0.0.1") or _listening(port):
        yield
        return
    server = make_server(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield
    finally:
        server.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = make_server(port)
    print(f"Lumen & Loom on http://localhost:{port}  (add ?fixed=1 for the fixed build)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
