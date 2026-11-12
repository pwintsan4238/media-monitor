"""Seed the configured news sources (configuration only; no articles). Idempotent.

Run: python -m app.seed
Endpoints below were each checked for a working feed or sitemap and for robots.txt permission.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import engine
from .models import Source

SOURCES = [
    dict(name="DVB Burmese", base_url="https://burmese.dvb.no", method="sitemap",
         sitemap_url="https://burmese.dvb.no/sitemap.xml",
         # 21 child sitemaps: 0.xml = static pages; the rest are 10,000-post chunks (/post/<id>) with a
         # useless lastmod (all migration dates). Newest posts = highest id = last chunk.
         scrape_config={"url_include": r"/post/\d+$", "child_order": "last", "sort": "id_desc",
                        "max_child_sitemaps": 1},
         description="Burmese-language edition of Democratic Voice of Burma. No RSS found; discovered via sitemap."),
    dict(name="RFA Burmese", base_url="https://www.rfa.org/burmese", method="sitemap",
         sitemap_url="https://www.rfa.org/arc/outboundfeeds/burmese/sitemap-news/",
         description="Radio Free Asia Burmese service. No RSS found; discovered via its Burmese news sitemap."),
    dict(name="Kachin News Group (Burmese)", base_url="https://burmese.kachinnews.com", method="rss",
         rss_url="https://burmese.kachinnews.com/feed/",
         sitemap_url="https://burmese.kachinnews.com/sitemap_index.xml",
         description="Burmese edition of Kachin News Group."),
    dict(name="Shwe Phee Myay", base_url="https://shwepheemyay.org", method="rss",
         rss_url="https://shwepheemyay.org/feed/",
         sitemap_url="https://shwepheemyay.org/sitemap_index.xml", description=""),
    dict(name="Shan News (Burmese)", base_url="https://burmese.shannews.org", method="rss",
         rss_url="https://burmese.shannews.org/feed",
         sitemap_url="https://burmese.shannews.org/sitemap_index.xml",
         description="Burmese edition of Shan Herald Agency for News. The site refuses plain page requests (HTTP 403); the feed works."),
    dict(name="Arakha Times", base_url="https://arakhatimes.com", method="rss",
         rss_url="https://arakhatimes.com/feed/",
         sitemap_url="https://arakhatimes.com/sitemap_index.xml", description=""),
    dict(name="Kantarawaddy Times", base_url="https://www.kantarawaddytimes.org", method="rss",
         rss_url="https://www.kantarawaddytimes.org/rss.xml",
         sitemap_url="https://www.kantarawaddytimes.org/sitemap_index.xml", description=""),
    dict(name="Dawei Watch", base_url="https://www.daweiwatch.com", method="rss",
         rss_url="https://www.daweiwatch.com/feed",
         sitemap_url="https://www.daweiwatch.com/sitemap_index.xml", description=""),
    dict(name="The Irrawaddy (Burmese)", base_url="https://burma.irrawaddy.com", method="rss",
         rss_url="https://burma.irrawaddy.com/feed",
         sitemap_url="https://burma.irrawaddy.com/sitemap_index.xml", description="Burmese edition of The Irrawaddy."),
]


def seed() -> int:
    added = 0
    with Session(engine()) as s:
        for row in SOURCES:
            if not s.scalar(select(Source).where(Source.base_url == row["base_url"])):
                s.add(Source(**row))
                added += 1
        s.commit()
    return added


if __name__ == "__main__":
    print(f"Added {seed()} new source(s).")
