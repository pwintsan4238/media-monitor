"""articles.duplicate_of_id, crawl_runs.stats

Idempotent (IF NOT EXISTS): 0001 builds tables from the live ORM metadata, so a fresh install
may already have these columns by the time this revision runs.
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE articles ADD COLUMN IF NOT EXISTS duplicate_of_id integer "
               "REFERENCES articles(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_articles_duplicate_of_id ON articles (duplicate_of_id)")
    op.execute("ALTER TABLE crawl_runs ADD COLUMN IF NOT EXISTS stats jsonb")


def downgrade():
    op.execute("ALTER TABLE crawl_runs DROP COLUMN IF EXISTS stats")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS duplicate_of_id")
