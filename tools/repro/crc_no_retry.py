# /// script
# requires-python = ">=3.11"
# dependencies = ["crc-sdk==1.0.0", "crc-framework==1.0.0"]
# ///
"""One dropped connection ends a read: crc-sdk never tries a download a second time.

Expected: a transient connection failure (a reset, a connection closed before the answer) is
tried again before the read fails. Observed: the read raises on the first dropped connection,
while the same server answers the next request. Offline and constructed: a local HTTP server
closes its first connection without answering and serves a valid 3-row IBTrACS CSV after that.
One private name is patched to point crc-sdk at it: crc_sdk._observed_sources._IBTRACS.

    uv run crc_no_retry.py
"""

import http.server
import threading
import urllib.request
from importlib import resources
from importlib.metadata import version

import crc_sdk._observed_sources
from crc_sdk import IBTrACS

CSV = (
    b"SID,ISO_TIME,LAT,LON,USA_WIND,USA_PRES\n"
    b" ,Year,degrees_north,degrees_east,kts,mb\n"
    b"2024181N09320,2024-07-08 06:00:00,28.6,-95.6,70,979\n"
    b"2024181N09320,2024-07-08 09:00:00,29.0,-95.7,70,980\n"
    b"2024181N09320,2024-07-08 12:00:00,29.6,-95.8,55,984\n"
)
seen: list[str] = []


class Flaky(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802  (http.server's name)
        seen.append("dropped" if not seen else "served")
        if seen[-1] == "dropped":  # close the connection without any response
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(CSV)))
        self.end_headers()
        self.wfile.write(CSV)

    def log_message(self, *args: object) -> None:
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_port}/ibtracs.ALL.list.v04r01.csv"
crc_sdk._observed_sources._IBTRACS = url  # the one private name patched

print(f"crc-sdk {version('crc-sdk')}, crc-framework {version('crc-framework')}")
print(f"server: {url} (1st connection closed unanswered, later ones served)")
print("call: IBTrACS(agency=IBTrACS.Agency.USA).read()")
print("expected: the dropped connection is tried again and the read returns 6 rows")
try:
    rows = IBTrACS(agency=IBTrACS.Agency.USA).read().table.num_rows
    first = f"{rows} rows"
except Exception as error:  # noqa: BLE001  the outcome is what is printed
    first = f"{type(error).__name__}: {error}"
requests_by_read = len(seen)
print(f"observed: read 1 -> {first}")
print(f"observed: requests the read made to the server: {requests_by_read}")
with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310  local server
    plain = f"HTTP {response.status}, {len(response.read())} bytes"
print(f"observed: plain urllib GET of the same URL right after -> {plain}")
rows = IBTrACS(agency=IBTrACS.Agency.USA).read().table.num_rows
print(f"observed: read 2 (same call again) -> {rows} rows")
sources = [p for p in resources.files("crc_sdk").rglob("*.py")]
mentions = [p.name for p in sources if "retry" in p.read_text("utf-8").lower()]
print(f"observed: installed crc_sdk .py files containing 'retry': {len(mentions)} "
      f"of {len(sources)}")  # fmt: skip
server.shutdown()
ok = "rows" not in first and requests_by_read == 1 and plain.startswith("HTTP 200")
print("REPRODUCED" if ok else "NOT REPRODUCED")
