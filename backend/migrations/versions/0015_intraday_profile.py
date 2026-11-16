"""intraday_profile_daily: 15-minute slices of the session, for the best time of day

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the table may already exist
    if "intraday_profile_daily" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "intraday_profile_daily",
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("window", sa.Integer, primary_key=True),
        sa.Column("mid", sa.Float, nullable=True),
        sa.Column("ask_min", sa.Float, nullable=True),
        sa.Column("bid_max", sa.Float, nullable=True),
        sa.Column("secs", sa.Float, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_intraday_profile_daily_instrument_id", "intraday_profile_daily", ["instrument_id"]
    )
    op.create_index("ix_intraday_profile_daily_date", "intraday_profile_daily", ["date"])


def downgrade() -> None:
    op.drop_table("intraday_profile_daily")
