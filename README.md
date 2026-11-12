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
