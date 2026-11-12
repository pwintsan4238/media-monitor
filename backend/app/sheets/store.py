"""Storage backends for the collector: an in-memory one (tests, dry runs) and Google Sheets."""
import logging

from .collector import COL, HEADERS, STATUS_HEADERS

log = logging.getLogger("mm.sheets")

ARTICLES, SEARCH, STATUS = "Articles", "Search", "Status"


class MemoryStore:
    def __init__(self, rows: list[list[str]] | None = None):
        self.rows: list[list[str]] = list(rows or [])
        self.status_rows: list[list[str]] = []

    def existing(self):
        urls = {r[COL["canonical_url"]] for r in self.rows}
        hashes = {r[COL["content_hash"]]: r[COL["url"]] for r in self.rows if r[COL["content_hash"]]}
        return urls, hashes

    def append(self, rows):
        self.rows.extend(rows)

    def write_status(self, rows):
        self.status_rows = rows


def search_formula() -> str:
    """Substring search over title, excerpt and full text. Substring (not whole-word) matching is
    what makes Burmese work, since Burmese has no spaces between words."""
    k = "LOWER(SUBSTITUTE($B$1,\"'\",\" \"))"
    return (
        '=IFERROR(QUERY(Articles!A2:O, "select A, B, C, D, H '
        f"where lower(C) contains '\" & {k} & \"' or lower(H) contains '\" & {k} & \"' "
        f"or lower(L) contains '\" & {k} & \"' "
        "order by A desc limit 300 "
        "label A 'Published (UTC)', B 'Source', C 'Title', D 'Link', H 'Excerpt'\", 0), \"No matches\")"
    )


class GoogleSheetStore:
    def __init__(self, sheet_id: str, service_account_info: dict):
        import gspread  # imported lazily so the rest of the app doesn't need it

        self.gc = gspread.service_account_from_dict(service_account_info)
        self.sh = self.gc.open_by_key(sheet_id)
        self._gspread = gspread
        self._layout()

    # -- layout -----------------------------------------------------------------
    def _ws(self, title: str):
        try:
            return self.sh.worksheet(title), False
        except self._gspread.WorksheetNotFound:
            return self.sh.add_worksheet(title=title, rows=1000, cols=max(len(HEADERS), 10)), True

    def _layout(self):
        titles = [w.title for w in self.sh.worksheets()]
        if ARTICLES not in titles and titles == ["Sheet1"]:
            self.sh.sheet1.update_title(ARTICLES)  # fresh sheet: reuse the default tab
        ws, new = self._ws(ARTICLES)
        if new or ws.row_values(1) != HEADERS:
            ws.update([HEADERS], "A1", value_input_option="RAW")
            ws.freeze(rows=1)
            ws.format("1:1", {"textFormat": {"bold": True}})
        self.articles = ws

        s, new = self._ws(SEARCH)
        if new:
            s.update([["Keywords", ""], ["Type a word or phrase in B1: it matches titles, excerpts and full text "
                                          "(substring match, so Burmese works). Leave blank to see the latest."],
                      [""]], "A1", value_input_option="RAW")
            s.update([[search_formula()]], "A4", value_input_option="USER_ENTERED")
            s.format("A1", {"textFormat": {"bold": True}})
            s.format("B1", {"backgroundColor": {"red": 1, "green": 0.96, "blue": 0.7}})
        st, new = self._ws(STATUS)
        if new:
            st.update([STATUS_HEADERS], "A1", value_input_option="RAW")
            st.freeze(rows=1)
        self.status = st

    # -- Store protocol ------------------------------------------------------------
    def existing(self):
        urls_col, key_cols = self.articles.batch_get(["D2:D", "M2:N"])
        urls = []
        for r in urls_col:
            urls.append(r[0] if r else "")
        canon, hashes = set(), {}
        for i, r in enumerate(key_cols):
            if r and r[0]:
                canon.add(r[0])
            if len(r) > 1 and r[1]:
                hashes[r[1]] = urls[i] if i < len(urls) else ""
        return canon, hashes

    def append(self, rows):
        for i in range(0, len(rows), 100):
            # RAW: values are stored as plain text and never evaluated, so web-sourced text
            # such as "=HYPERLINK(...)" cannot run as a formula.
            self.articles.append_rows(rows[i:i + 100], value_input_option="RAW",
                                      insert_data_option="INSERT_ROWS", table_range="A1")
        log.info("appended %d rows", len(rows))

    def write_status(self, rows):
        self.status.clear()
        self.status.update([STATUS_HEADERS, *rows], "A1", value_input_option="RAW")
