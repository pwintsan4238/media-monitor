"""Crawl the configured sources and add new articles to a Google Sheet.

    python -m app.sheet_sync               # real run (needs SHEET_ID + service account credentials)
    python -m app.sheet_sync --dry-run     # crawl for real, write nothing, print what would be added
    python -m app.sheet_sync --only dvb    # limit to sources whose name contains this text

Credentials (never commit them):
    SHEET_ID                      the long id in the Sheet's URL
    GOOGLE_SERVICE_ACCOUNT_JSON   the service-account key file's contents, or
    GOOGLE_SERVICE_ACCOUNT_FILE   a path to that file
"""
import argparse
import json
import logging
import os
import sys

from .seed import SOURCES
from .sheets import collector
from .sheets.store import GoogleSheetStore, MemoryStore


def load_credentials() -> dict:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not raw and path:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    if not raw:
        raise SystemExit("Set GOOGLE_SERVICE_ACCOUNT_JSON (key contents) or GOOGLE_SERVICE_ACCOUNT_FILE (path).")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit("The Google service-account credentials are not valid JSON.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="crawl but do not write to the Sheet")
    ap.add_argument("--only", default="", help="only sources whose name contains this text")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs are noisy and not useful here

    sources = [s for s in SOURCES if args.only.lower() in s["name"].lower()]
    if not sources:
        raise SystemExit(f"No source name contains {args.only!r}")

    if args.dry_run:
        store = MemoryStore()
    else:
        sheet_id = os.environ.get("SHEET_ID")
        if not sheet_id:
            raise SystemExit("Set SHEET_ID to the id from the Google Sheet's URL.")
        store = GoogleSheetStore(sheet_id, load_credentials())

    statuses = collector.run(sources, store)
    print("\nsource | status | found | new | already there | deferred")
    for s in statuses:
        print(f"{s.source} | {s.status} | {s.found} | {s.new} | {s.skipped} | {s.deferred}")
        if s.note and s.status != "ok":
            print(f"    note: {s.note[:200]}")
    if args.dry_run:
        print(f"\nDry run: {len(store.rows)} rows would be added; nothing was written.")
    # Fail the workflow only if EVERY source failed (e.g. credentials or network problem), so that
    # one flaky site doesn't turn the whole schedule red.
    return 1 if statuses and all(s.status in ("failed", "restricted") for s in statuses) else 0


if __name__ == "__main__":
    sys.exit(main())
