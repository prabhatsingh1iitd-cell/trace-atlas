"""Serve only the viewer and exported results on loopback; no directory listing."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="output")
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    code = Path(__file__).resolve().parent
    output = Path(a.output).resolve()
    routes = {
        "/": code / "viewer.html",
        "/viewer.html": code / "viewer.html",
        "/viewer.css": code / "viewer.css",
        "/viewer.js": code / "viewer.js",
    }
    for name in [
        "results.json",
        "quality.json",
        "trace_assignments.jsonl",
        "call_assignments.jsonl",
        "validation.json",
    ]:
        routes["/" + name] = output / name

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = routes.get(urlsplit(self.path).path)
            if path is None or not path.is_file():
                self.send_error(404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".jsonl": "application/x-ndjson; charset=utf-8",
                }[path.suffix],
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    print(f"Local viewer: http://127.0.0.1:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
