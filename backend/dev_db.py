"""Local dev PostgreSQL (embedded, no Docker needed).

Keeps running in the foreground and writes its connection URI to .dev_db_uri.
Data lives in ~/mm-pgdata (short path on purpose: Windows path-length limits).
"""
import pathlib
import socket
import subprocess
import time

import pgserver

data = pathlib.Path.home() / "mm-pgdata"
uri_file = pathlib.Path(__file__).with_name(".dev_db_uri")


def uri_from_running_server(timeout: float = 120) -> str:
    """After an unclean shutdown Postgres runs crash recovery, which can exceed pgserver's 10s start
    timeout even though the server comes up fine. Wait for it via postmaster.pid instead."""
    pid_file = data / "postmaster.pid"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            port = int(pid_file.read_text().splitlines()[3])
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
            return f"postgresql://postgres:@127.0.0.1:{port}/postgres"
        except (OSError, IndexError, ValueError):
            time.sleep(2)
    raise SystemExit("Postgres did not come up")


try:
    srv = pgserver.get_server(data, cleanup_mode=None)
    uri = srv.get_uri()
except (subprocess.TimeoutExpired, AssertionError):
    print("pgserver start timed out; waiting for the server to finish recovery", flush=True)
    uri = uri_from_running_server()

uri_file.write_text(uri)
print("Postgres ready:", uri, flush=True)
while True:
    time.sleep(3600)
