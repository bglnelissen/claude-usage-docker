#!/usr/bin/env python3
"""HTTP service around claude_usage, for the container.

GET /        {"current": 14, "weekly": 50, "current_resets_at": ..., ...}
GET /health  whether the service is up, and how the last measurement went

Claude Code is only called when a request comes in and the previous
measurement is older than CACHE_SECONDS. Without visitors nothing happens.
A measurement costs no tokens (see claude_usage.py).
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import claude_usage

PORT = int(os.environ.get("PORT", "8130"))
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "60"))
# When a measurement fails, the previous one stays usable this long (with "stale": true).
STALE_MAX_SECONDS = int(os.environ.get("STALE_MAX_SECONDS", "3600"))

_lock = threading.Lock()
_state: dict = {"data": None, "ok_at": None, "tried_at": None, "error": None}


def current_usage() -> tuple[int, dict]:
    # The lock covers the measurement itself: concurrent requests wait for the
    # same measurement instead of each starting their own claude.
    with _lock:
        now = time.monotonic()
        if _state["tried_at"] is None or now - _state["tried_at"] >= CACHE_SECONDS:
            _state["tried_at"] = now
            try:
                _state["data"] = claude_usage.fetch()
                _state["ok_at"] = now
                _state["error"] = None
            except claude_usage.UsageError as e:
                _state["error"] = str(e)
                print(f"measurement failed: {e}", flush=True)
        data, ok_at, error = _state["data"], _state["ok_at"], _state["error"]

    if data is None:
        return 503, {"error": error}
    if error:
        if now - ok_at > STALE_MAX_SECONDS:
            return 503, {"error": error}
        return 200, {**data, "stale": True, "error": error}
    return 200, data


def health() -> tuple[int, dict]:
    with _lock:
        return 200, {"ok": True, "last_fetched_at": (_state["data"] or {}).get("fetched_at"),
                     "last_error": _state["error"]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/usage"):
            status, body = current_usage()
        elif path == "/health":
            status, body = health()
        else:
            status, body = 404, {"error": "unknown path, use / or /health"}
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        # So a dashboard in the browser can fetch it too.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        if self.path != "/health":  # Docker's healthcheck would fill the log every minute
            print(f"{self.address_string()} {format % args}", flush=True)


if __name__ == "__main__":
    print(f"claude-usage listening on port {PORT}, cache {CACHE_SECONDS} s", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
