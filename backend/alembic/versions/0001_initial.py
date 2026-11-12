"""initial schema

Creates all tables from the ORM metadata, then adds what the ORM can't express:
extensions, the generated full-text column, and search indexes.
"""
from alembic import op

from app import models  # noqa: F401
from app.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # pg_trgm ships with standard PostgreSQL (Docker/production) but not with the
    # embedded dev server; make trigram indexes optional so both work.
    has_trgm = bool(bind.exec_driver_sql(
        "SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'").scalar())
    if has_trgm:
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    Base.metadata.create_all(bind)
    # 'simple' config: language-neutral, safe for Myanmar script (no stemming).
    # Title is weighted A, excerpt B, body C.
    op.execute(
        """
        ALTER TABLE articles ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('simple', coalesce(excerpt, '')), 'B') ||
            setweight(to_tsvector('simple', coalesce(content, '')), 'C')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_articles_search_vector ON articles USING GIN (search_vector)")
    # Trigram indexes allow substring matching, which matters for Myanmar (no word spaces).
    if has_trgm:
        op.execute("CREATE INDEX ix_articles_title_trgm ON articles USING GIN (title gin_trgm_ops)")
        op.execute("CREATE INDEX ix_articles_content_trgm ON articles USING GIN (content gin_trgm_ops)")


def downgrade():
    Base.metadata.drop_all(op.get_bind())
