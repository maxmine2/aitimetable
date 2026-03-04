"""Local HTTP server for the timetable viewer with update endpoint."""

import argparse
import http.server
import json
import re
import subprocess
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 8764

# ---------------------------------------------------------------------------
# Security — request filtering & rate limiting
# ---------------------------------------------------------------------------

# Only these files may be served (relative to CWD). Everything else → 403.
_ALLOWED_FILES = frozenset({
    "/timetable.html",
    "/nsu_data.json",
    "/favicon.ico",
})

# API paths handled separately
_API_PATHS = frozenset({
    "/api/update",
    "/api/update/status",
})

# Patterns that vulnerability scanners and bots typically probe
_BLOCKED_PATH_RE = re.compile(
    r"(?i)"
    r"(?:\.\.)"                                       # path traversal
    r"|(?:\.(?:env|git|svn|htaccess|htpasswd|ds_store|bak|old|orig|swp|sql|log|config))" # sensitive files
    r"|(?:/(?:wp-|wordpress|admin|phpmyadmin|phpinfo|cgi-bin|\.well-known|xmlrpc|"
    r"actuator|manager|solr|struts|jenkins|jmx|console|invoke|debug|trace|"
    r"telescope|_profiler|elfinder|filemanager|upload|shell|eval|cmd|exec|"
    r"setup|install|config|backup|dump|db|database|mysql|postgres|sqlite|"
    r"api/v\d|graphql|rest|swagger|json/|yaml/|info|status|health|metrics|"
    r"\.php|\.asp|\.jsp|\.cgi|\.pl|\.py|\.rb|\.sh|\.bat))"
    r"|(?:%(?:00|2e|5c|c0|c1|25))"                   # encoded traversal / null bytes
    r"|(?:[<>\"';])"                                  # XSS / injection chars in URL
)

# User-Agent substrings associated with automated scanners
_BLOCKED_UA_RE = re.compile(
    r"(?i)"
    r"(?:nmap|nikto|sqlmap|dirbuster|gobuster|ffuf|wfuzz|nuclei|masscan|"
    r"zap|burp|hydra|medusa|skipfish|acunetix|nessus|openvas|whatweb|"
    r"curl/|wget/|python-requests/|httpclient|Go-http-client|libwww-perl|"
    r"scrapy|zgrab|censys|shodan)"
)



# ---------------------------------------------------------------------------
# Update state — guarded by a lock
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_updating = False
_last_finish: float = 0.0  # epoch when the last update finished
_MIN_INTERVAL = 600  # seconds (10 minutes)

# Progress tracking (written by updater thread, read by status endpoint)
_progress_current = 0
_progress_total = 0
_progress_phase = ""  # e.g. "faculties", "groups"

_PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\]")


def _run_update_bg() -> None:
    """Run analysis.py in a background thread, streaming progress."""
    global _updating, _last_finish, _progress_current, _progress_total, _progress_phase
    _result_box: dict = {}

    try:
        with _lock:
            _progress_current = 0
            _progress_total = 0
            _progress_phase = "Запуск…"

        proc = subprocess.Popen(
            [sys.executable, "-u", "analysis.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )

        output_lines: list[str] = []
        for line in proc.stdout:                 # type: ignore[union-attr]
            output_lines.append(line)
            # Parse progress from "[current/total]"
            m = _PROGRESS_RE.search(line)
            if m:
                with _lock:
                    _progress_current = int(m.group(1))
                    _progress_total = int(m.group(2))
                    _progress_phase = "Загрузка расписаний"
            elif "Fetching list of faculties" in line:
                with _lock:
                    _progress_phase = "Факультеты…"
            elif "Discovered" in line and "unique groups" in line:
                # Extract total from "Discovered 690 unique groups …"
                dm = re.search(r"Discovered (\d+) unique groups", line)
                if dm:
                    with _lock:
                        _progress_total = int(dm.group(1))
                        _progress_phase = "Загрузка расписаний"

        proc.wait(timeout=300)
        success = proc.returncode == 0
        tail = "".join(output_lines[-40:])

        with _lock:
            if success:
                _progress_phase = "Готово"
            else:
                _progress_phase = "Ошибка"
            _result_box_store["result"] = {
                "status": "ok" if success else "error",
                "message": "Update completed." if success else "Update failed.",
                "output": tail[-2000:],
            }
    except subprocess.TimeoutExpired:
        with _lock:
            _progress_phase = "Таймаут"
            _result_box_store["result"] = {"status": "error", "message": "Update timed out (5 min)."}
        proc.kill()  # type: ignore[possibly-undefined]
    except Exception as exc:
        with _lock:
            _progress_phase = "Ошибка"
            _result_box_store["result"] = {"status": "error", "message": str(exc)}
    finally:
        with _lock:
            _updating = False
            _last_finish = time.time()


# Shared dict to pass result from thread back to the POST response
_result_box_store: dict = {}


def _start_update() -> dict:
    """Try to start an update. Returns immediate status."""
    global _updating

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
        _result_box_store.pop("result", None)

    t = threading.Thread(target=_run_update_bg, daemon=True)
    t.start()
    return {"status": "started", "message": "Update started."}


def _status() -> dict:
    """Return current update status with progress info."""
    with _lock:
        if _updating:
            return {
                "status": "busy",
                "current": _progress_current,
                "total": _progress_total,
                "phase": _progress_phase,
            }
        # Check if a result is available from a just-finished update
        result = _result_box_store.get("result")
        if result:
            out = dict(result)
            out["current"] = _progress_current
            out["total"] = _progress_total
            return out
        elapsed = time.time() - _last_finish
        if _last_finish and elapsed < _MIN_INTERVAL:
            return {"status": "cooldown", "retry_after": int(_MIN_INTERVAL - elapsed)}
        return {"status": "idle"}


class Handler(http.server.SimpleHTTPRequestHandler):

    # Disable directory listings entirely
    def list_directory(self, path):
        self.send_error(403)
        return None

    # ---- security gate (runs before every request) ----
    def _guard(self) -> bool:
        """Return True if the request is allowed. Sends error & returns False otherwise."""
        # 1. Block bad user-agents
        ua = self.headers.get("User-Agent", "")
        if _BLOCKED_UA_RE.search(ua):
            self.send_error(403, "Forbidden")
            return False

        # 2. Block suspicious URL patterns
        if _BLOCKED_PATH_RE.search(self.path):
            self.send_error(403, "Forbidden")
            return False

        # 4. Reject oversized headers (Content-Length for POST)
        cl = self.headers.get("Content-Length")
        if cl:
            try:
                if int(cl) > 4096:
                    self.send_error(413, "Payload Too Large")
                    return False
            except ValueError:
                self.send_error(400, "Bad Request")
                return False

        return True

    def _add_security_headers(self):
        """Append hardening headers to every response."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
        self.send_header("Permissions-Policy",
                         "camera=(), microphone=(), geolocation=()")

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._guard():
            return
        if self.path == "/api/update":
            self._json_response(_start_update())
        else:
            self.send_error(404)

    def do_GET(self):
        if not self._guard():
            return
        if self.path == "/api/update/status":
            self._json_response(_status())
            return

        # Redirect / -> /timetable.html
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/timetable.html")
            self.end_headers()
            return

        # Whitelist static files
        clean = self.path.split("?")[0].split("#")[0]
        if clean not in _ALLOWED_FILES:
            self.send_error(403, "Forbidden")
            return

        super().do_GET()

    # Block all other HTTP methods
    def do_PUT(self):     self.send_error(405, "Method Not Allowed")
    def do_DELETE(self):  self.send_error(405, "Method Not Allowed")
    def do_PATCH(self):   self.send_error(405, "Method Not Allowed")
    def do_OPTIONS(self): self.send_error(405, "Method Not Allowed")

    def end_headers(self):
        self._add_security_headers()
        super().end_headers()

    def log_message(self, fmt, *args):
        if len(args) >= 1 and isinstance(args[0], str) and "/api/" in args[0]:
            return
        super().log_message(fmt, *args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Timetable Viewer HTTP server")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to listen on (default: {DEFAULT_PORT})")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1, use 0.0.0.0 for all interfaces)")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open browser on start")
    args = parser.parse_args()

    with http.server.HTTPServer((args.host, args.port), Handler) as srv:
        display_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0", "") else args.host
        url = f"http://{display_host}:{args.port}/timetable.html"
        print(f"Serving at {url}  (bound to {args.host})")
        if not args.no_open:
            webbrowser.open(url)
        srv.serve_forever()
