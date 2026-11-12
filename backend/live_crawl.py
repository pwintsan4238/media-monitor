"""Crawl every enabled source for real and print what was stored. Usage: python live_crawl.py [name-substring]"""
import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crawler.pipeline import crawl_source
from app.db import engine
from app.models import Article, Source

only = sys.argv[1].lower() if len(sys.argv) > 1 else ""
with Session(engine()) as db:
    for src in db.scalars(select(Source).where(Source.enabled).order_by(Source.id)):
        if only and only not in src.name.lower():
            continue
        run = crawl_source(db, src, trigger="manual")
        total = db.scalar(select(func.count()).select_from(Article).where(Article.source_id == src.id))
        a = db.scalars(select(Article).where(Article.source_id == src.id).order_by(Article.published_at.desc().nullslast()).limit(1)).first()
        print(f"\n== {src.name}: {run.status} | discovered={run.discovered} new={run.new_count} "
              f"updated={run.updated_count} | stored_total={total} | {run.stats}", flush=True)
        if run.log:
            print("   log:", run.log.replace("\n", " | ")[:400], flush=True)
        if a:
            print(f"   e.g. [{a.published_at}] {a.title[:70]} | {len(a.content)} chars | lang={a.language} | cat={a.category}", flush=True)
