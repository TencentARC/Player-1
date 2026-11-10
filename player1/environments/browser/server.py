"""Local static asset server with an ephemeral port."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class AssetServer:
    def __init__(self, root: Path, *, port: int = 0):
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", port), partial(QuietHandler, directory=str(root.resolve())),
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
