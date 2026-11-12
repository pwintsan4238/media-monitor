"""Run real discovery against every seeded source and print a feasibility table (stores nothing)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.discovery import discover
from app.crawler.http import Fetcher
from app.db import engine
from app.models import Source

with Session(engine()) as s:
    for src in s.scalars(select(Source).order_by(Source.id)):
        f = Fetcher()
        try:
            r = discover(src, f)
        finally:
            f.close()
        n = len(r.items)
        print(f"\n{src.name}: method={r.method} items={n} "
              f"dated={sum(1 for i in r.items if i.published_at)} titled={sum(1 for i in r.items if i.title)} "
              f"full_text={sum(1 for i in r.items if i.content_html)} restricted={r.restricted}")
        for e in r.errors:
            print("   ERR", e[:200])
        if r.items:
            i = r.items[0]
            print("   e.g.", i.published_at, (i.title or "")[:60], i.url[:90])
