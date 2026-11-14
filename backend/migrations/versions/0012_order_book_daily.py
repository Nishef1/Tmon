"""order_book_daily: the 5-level book reduced to one row per instrument and day

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_FLOATS = (
    "close_bid_price close_ask_price close_bid_volume close_ask_volume close_imbalance "
    "open_imbalance early_imbalance tw_imbalance tw_spread tw_depth_value tw_size_ratio "
    "frac_buy_queue frac_sell_queue peak_queue_volume"
).split()


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the table may already exist
    if "order_book_daily" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "order_book_daily",
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("n_events", sa.Integer, nullable=False),
        sa.Column("close_bid_count", sa.Integer, nullable=True),
        sa.Column("close_ask_count", sa.Integer, nullable=True),
        *[sa.Column(c, sa.Float, nullable=True) for c in _FLOATS],
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_order_book_daily_instrument_id", "order_book_daily", ["instrument_id"])
    op.create_index("ix_order_book_daily_date", "order_book_daily", ["date"])


def downgrade() -> None:
    op.drop_table("order_book_daily")
