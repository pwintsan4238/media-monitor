# Media Monitor

A focused media-monitoring tool for a **fixed set of news websites**: it collects their articles from RSS feeds
and sitemaps, stores them in PostgreSQL, and (planned) lets you search them and generate source-cited press briefs.
It is not a general web search engine. Built for Burmese (Myanmar Unicode) and English content.

The whole app is login-gated.

## Status

| Phase | Feature | State |
|---|---|---|
| 1 | Database schema + migrations, login-gated API, Next.js shell | Done |
| 2 | Source management, robots.txt-aware RSS / sitemap discovery | Done |
| 3 | Article extraction, storage, duplicate detection, versioning | Done |
| 4 | Full-text search (keywords, phrases, AND/OR/NOT, filters, highlighting) | **Not built yet** |
| 5 | AI press-brief generator with citation validation | **Not built yet** |
| 6 | Scheduled crawling + monitoring dashboard | **Not built yet** (crawl manually from Admin) |
| 7 | PDF export, deployment hardening | **Not built yet** |

Until Phase 4 the search box is a placeholder. What works today: sign in, manage sources, test a source,
crawl it, and see how many articles were stored.

## Google Sheet mode: no server, no hosting

The same crawler can run free on a schedule in **GitHub Actions** and write new articles into a **Google Sheet**
that you search and filter. Nothing needs to be hosted. The Sheet gets three tabs:

* **Articles**: one row per article (title, source, date, link, author, category, excerpt, full text, ...).
* **Search**: type a word or phrase in cell `B1` and the matching articles appear below. It matches titles,
  excerpts and full text with substring matching, so Burmese works. Leave it blank to see the latest.
* **Status**: one line per source from the last run, including any source that failed or was blocked.

Setup (about 10 minutes, once):

1. Create an empty Google Sheet. Copy its ID: the long string in its URL between `/d/` and `/edit`.
2. In the [Google Cloud console](https://console.cloud.google.com/): create a project, enable the
   **Google Sheets API**, then create a **service account** and download a **JSON key** for it.
3. Open the Sheet, press **Share**, and add the service account's email (the `client_email` in the key file) as **Editor**.
4. In this GitHub repo go to **Settings > Secrets and variables > Actions** and add two secrets:
   `SHEET_ID` (the ID from step 1) and `GOOGLE_SERVICE_ACCOUNT_JSON` (the full contents of the key file).
   Or with the GitHub CLI: `gh secret set GOOGLE_SERVICE_ACCOUNT_JSON < key.json`.
5. Open the **Actions** tab, choose **Collect articles into Google Sheet**, and press **Run workflow**.
   After that it runs by itself every 3 hours.

Try it without any Google setup: `cd backend && python -m app.sheet_sync --dry-run` crawls the real sites and
prints what it would add, writing nothing.

Things to know:

* Rows are append-only: an article that is edited after it was collected is not updated in the Sheet.
* Large sites fill in over several runs (about 40 article pages per source per run), newest first.
* GitHub's servers can be blocked by some sites; the **Status** tab says so rather than pretending a source is monitored.
* GitHub pauses scheduled workflows on repositories with no activity for 60 days; re-enable them in the Actions tab.
* Keep the Sheet **private**. It holds publishers' article text, which you should not redistribute.
* The login, Admin page, search page and press-brief features belong to the full web app below, which needs a server.

## How collection works

1. **Discover** article URLs per source: RSS first, then sitemap (per-source tuning in `scrape_config`).
2. **Be polite:** honest User-Agent, `robots.txt` honoured, per-host rate limit, no bypassing of 403s,
   paywalls or login walls. If a source cannot be crawled it is reported as failing/limited, never silently "monitored".
3. **Extract:** full text from the feed if present, otherwise the article page via `trafilatura`
   (a per-run page budget means large archives fill in over several runs, newest first).
4. **Store:** canonical-URL + content-hash de-duplication; changed articles keep their old version;
   original publication dates are never overwritten; missing metadata stays empty rather than guessed.

## Quick start (Docker)

Requires Docker with Compose.

```bash
cp .env.example .env                       # then set POSTGRES_PASSWORD in .env
pip install bcrypt
python backend/set_admin_password.py       # prompts for the admin login; writes the hash + a JWT secret to .env
docker compose up -d --build
```

Open http://localhost:3000, sign in, go to **Admin**, and press **Crawl now** on each source.
The nine configured Burmese-language sources are added automatically on first start (edit `backend/app/seed.py`
to change them, or manage them in the Admin page).

### Deploying on a server

* Put a TLS-terminating reverse proxy (Caddy, nginx, Traefik) in front of the `frontend` container.
  Only the frontend needs to be reachable; the backend and database stay on the internal Docker network.
* Use a strong admin password and a long random `JWT_SECRET`. Keep `.env` out of version control (it is git-ignored).
* The database lives in the `pgdata` volume. Back it up.

## Local development (no Docker)

Requires Python 3.12+ and Node 22+.

```bash
python -m venv ~/mm-venv && ~/mm-venv/bin/pip install -r backend/requirements.txt pgserver
cd backend
python dev_db.py &                 # embedded PostgreSQL, writes .dev_db_uri (no Docker needed)
python -m alembic upgrade head
python -m app.seed
python set_admin_password.py
python -m uvicorn app.main:app --port 8000
# second terminal
cd frontend && npm install && npm run build && npm run start -- -p 3100
```

Run the tests: `cd backend && python -m pytest` (needs the dev database running).
On Windows keep the project path short; very long paths break Python and Node tooling.

## Known limitations

* **Burmese search:** Burmese has no spaces between words, so PostgreSQL's built-in tokenizer matches whole
  runs of text. Phase 4 will add substring matching (`pg_trgm`, available in the Docker database image).
* Some feeds have no full text or images; those articles are stored with what the feed provides.
* Possible Zawgyi-encoded text is detected and flagged in the crawl log but not converted.
* Stored article text is for your own indexing and analysis. Search results link to the originals; respect
  each publisher's terms and copyright before redistributing content.

## Layout

```
backend/   FastAPI app, crawler (app/crawler), Alembic migrations, tests
frontend/  Next.js + Tailwind UI
docker-compose.yml, .env.example
```
