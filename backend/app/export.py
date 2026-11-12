"""CSV export of stored articles, for opening in Google Sheets / Excel."""
import csv
import io
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auth
from .db import get_db
from .models import Article, Source

router = APIRouter(prefix="/api", dependencies=[auth.Authed])

COLUMNS = ["id", "source", "title", "published_at", "author", "category", "language", "url", "excerpt",
           "keywords", "indexed_at", "duplicate_of_id"]


def safe_cell(v) -> str:
    """Neutralise spreadsheet formula injection: article text comes from the open web, and a cell that
    starts with = + - @ (or tab/CR) would be executed as a formula by Sheets/Excel."""
    s = "" if v is None else (v.isoformat() if isinstance(v, datetime) else str(v))
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/articles/export.csv")
def export_articles(
    source_id: int | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    limit: int = Query(5000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    q = select(Article, Source.name).join(Source, Source.id == Article.source_id)
    if source_id:
        q = q.where(Article.source_id == source_id)
    if date_from:
        q = q.where(Article.published_at >= datetime.combine(date_from, datetime.min.time(), timezone.utc))
    if date_to:
        q = q.where(Article.published_at < datetime.combine(date_to, datetime.max.time(), timezone.utc))
    q = q.order_by(Article.published_at.desc().nullslast(), Article.id.desc()).limit(limit)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for a, source in db.execute(q):
        w.writerow([safe_cell(x) for x in (
            a.id, source, a.title, a.published_at, a.author, a.category, a.language, a.url, a.excerpt,
            "; ".join(a.keywords or []), a.indexed_at, a.duplicate_of_id)])
    # UTF-8 BOM so Excel/Sheets detect the encoding and Burmese text isn't garbled.
    body = "﻿" + buf.getvalue()
    name = f"articles-{datetime.now(timezone.utc):%Y-%m-%d}.csv"
    return Response(body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
