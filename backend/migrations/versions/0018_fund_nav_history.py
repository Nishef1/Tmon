"""fund_nav_history: daily NAV, units and asset mix from each fund's own website

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

FLOATS = (
    "issue_nav",
    "cancel_nav",
    "statistical_nav",
    "base_nav",
    "units",
    "base_units",
    "units_issued",
    "units_revoked",
    "net_asset",
    "leverage",
    "unitholders",
    "stock_pct",
    "top5_pct",
    "bond_pct",
    "commodity_pct",
    "cash_pct",
    "fund_unit_pct",
    "other_pct",
)


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the table may exist
    if "fund_nav_history" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "fund_nav_history",
        sa.Column("reg_no", sa.String(16), primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), nullable=True),
        sa.Column("platform", sa.String(16), nullable=True),
        *[sa.Column(c, sa.Float, nullable=True) for c in FLOATS],
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fund_nav_history_instrument_id", "fund_nav_history", ["instrument_id"])


def downgrade() -> None:
    op.drop_index("ix_fund_nav_history_instrument_id", table_name="fund_nav_history")
    op.drop_table("fund_nav_history")
