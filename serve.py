"""Local HTTP server for the timetable viewer with update endpoint."""

import http.server
import json
import subprocess
import sys
import threading
import time
import webbrowser

PORT = 8764

# ---------------------------------------------------------------------------
# Update state — guarded by a lock
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_updating = False
_last_finish: float = 0.0  # epoch when the last update finished
_MIN_INTERVAL = 600  # seconds (10 minutes)


def _run_update() -> dict:
    """Run analysis.py in a subprocess. Returns a status dict."""
    global _updating, _last_finish

    with _lock:
        if _updating:
            return {"status": "busy", "message": "Update already in progress."}
        elapsed = time.time() - _last_finish
        if _last_finish and elapsed < _MIN_INTERVAL:
            remaining = int(_MIN_INTERVAL - elapsed)
            return {
                "status": "cooldown",
                "message": f"Please wait {remaining}s before the next update.",
                "retry_after": remaining,
            }
        _updating = True

    try:
        result = subprocess.run(
            [sys.executable, "analysis.py"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 min hard limit
        )
        success = result.returncode == 0
        return {
            "status": "ok" if success else "error",
            "message": "Update completed." if success else "Update failed.",
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Update timed out (5 min)."}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
    finally:
        with _lock:
            _updating = False
            _last_finish = time.time()


def _status() -> dict:
    """Return current update status without triggering an update."""
    with _lock:
        if _updating:
            return {"status": "busy"}
        elapsed = time.time() - _last_finish
        if _last_finish and elapsed < _MIN_INTERVAL:
            return {"status": "cooldown", "retry_after": int(_MIN_INTERVAL - elapsed)}
        return {"status": "idle"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/update":
            result = _run_update()
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path == "/api/update/status":
            result = _status()
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt, *args):
        # Keep default logging but suppress noisy static-file GETs
        if len(args) >= 1 and isinstance(args[0], str) and args[0].startswith("GET /api"):
            return
        super().log_message(fmt, *args)


with http.server.HTTPServer(("", PORT), Handler) as srv:
    url = f"http://localhost:{PORT}/timetable.html"
    print(f"Serving at {url}")
    webbrowser.open(url)
    srv.serve_forever()
