import html
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import read_json, write_json

EVENTS = "events.json"
KEEP = 300


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Status:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = read_json(EVENTS, [])
        self.queue: list[str] = []
        self.started = self.last_run = self.next_run = None

    def begin(self) -> None:
        with self.lock:
            self.started, self.queue = now().isoformat(), []

    def finish(self, interval: int) -> None:
        with self.lock:
            self.started, self.queue = None, []
            self.last_run = now().isoformat()
            self.next_run = (now() + timedelta(seconds=interval)).isoformat()

    def event(self, kind: str, names: str, error: str | None = None) -> None:
        with self.lock:
            if names in self.queue:
                self.queue.remove(names)
            self.events.insert(
                0, {"time": now().isoformat(), "kind": kind, "names": names, "error": error}
            )
            del self.events[KEEP:]
            write_json(EVENTS, self.events)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "started": self.started,
                "last_run": self.last_run,
                "next_run": self.next_run,
                "queue": list(self.queue),
                "events": list(self.events),
            }


STYLE = """
body { font: 15px/1.5 system-ui, sans-serif; color: #222; }
body { margin: 2rem auto; max-width: 70rem; padding: 0 1rem; }
h2 { margin-top: 2rem; font-size: 1.1rem; }
table { border-collapse: collapse; width: 100%; }
td { border-top: 1px solid #ddd; padding: .3rem .5rem; vertical-align: top; }
td:first-child { white-space: nowrap; color: #666; }
pre { margin: 0; white-space: pre-wrap; font-size: .85em; color: #a00; }
.empty { color: #888; }
"""


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="empty">none</p>'
    cells = ("".join(f"<td>{cell}</td>" for cell in row) for row in rows)
    return "<table>" + "".join(f"<tr>{row}</tr>" for row in cells) + "</table>"


def page(s: dict) -> str:
    e = html.escape
    if s["started"]:
        state = f"Running since {e(s['started'])}"
    else:
        last, next_ = s["last_run"] or "never", s["next_run"] or "unknown"
        state = f"Idle. Last run {e(last)}, next run {e(next_)}"
    issues = [ev for ev in s["events"] if ev["error"]]
    migrated = [ev for ev in s["events"] if ev["kind"] == "synced"]
    return f"""<!doctype html>
<meta charset="utf-8"><meta http-equiv="refresh" content="30">
<title>frameio-sync</title><style>{STYLE}</style>
<h1>frameio-sync</h1>
<p>{state}</p>
<h2>Queue ({len(s["queue"])})</h2>
{_table([[e(n)] for n in s["queue"]])}
<h2>Issues ({len(issues)})</h2>
{_table([[e(ev["time"]), e(ev["names"]), f"<pre>{e(ev['error'])}</pre>"] for ev in issues])}
<h2>Migrated ({len(migrated)})</h2>
{_table([[e(ev["time"]), e(ev["names"])] for ev in migrated])}
"""


def serve(status: Status, port: int) -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = page(status.snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_port
