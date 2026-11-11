"""market_index_daily and macro_series

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

from tmon.storage.models import JsonType

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _missing(name: str) -> bool:
    # 0001 builds the whole current metadata on a fresh database, so these may already exist
    return not sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _missing("market_index_daily"):
        op.create_table(
            "market_index_daily",
            sa.Column("index_code", sa.String(32), primary_key=True),
            sa.Column("date", sa.Date, primary_key=True),
            sa.Column("close", sa.Float, nullable=False),
            sa.Column("high", sa.Float),
            sa.Column("low", sa.Float),
            sa.Column("source_url", sa.Text),
            sa.Column("fetched_at", sa.DateTime(timezone=True)),
        )
    if _missing("macro_series"):
        op.create_table(
            "macro_series",
            sa.Column("series", sa.String(64), primary_key=True),
            sa.Column("source", sa.String(64), primary_key=True),
            sa.Column("ref_period", sa.Date, primary_key=True),
            sa.Column("value", sa.Float, nullable=False),
            sa.Column("release_date", sa.Date),
            sa.Column("meta", JsonType),
            sa.Column("source_url", sa.Text),
            sa.Column("fetched_at", sa.DateTime(timezone=True)),
        )


def downgrade() -> None:
    op.drop_table("macro_series")
    op.drop_table("market_index_daily")
