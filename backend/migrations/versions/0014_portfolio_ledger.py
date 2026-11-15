"""portfolio_trades (the ledger), broker_links (Mofid), holdings.stop_raw / stop_set_on

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _portfolio_fk(primary_key: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "portfolio_id",
        sa.Integer,
        sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
        primary_key=primary_key,
        index=not primary_key,
    )


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so these may already exist
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "portfolio_trades" not in existing:
        op.create_table(
            "portfolio_trades",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            _portfolio_fk(),
            sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
            sa.Column("side", sa.String(8), nullable=False),
            sa.Column("date", sa.Date, nullable=False),
            sa.Column("shares", sa.Float),
            sa.Column("price", sa.Float),
            sa.Column("amount", sa.Float),
            sa.Column("fee", sa.Float),
            sa.Column("cash_delta", sa.Float, nullable=False, server_default="0"),
            sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
            sa.Column("external_id", sa.String(80), index=True),
            sa.Column("note", sa.String(300)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_portfolio_trades_portfolio_date", "portfolio_trades", ["portfolio_id", "date"]
        )
    if "broker_links" not in existing:
        op.create_table(
            "broker_links",
            _portfolio_fk(primary_key=True),
            sa.Column("broker", sa.String(16), nullable=False, server_default="mofid"),
            sa.Column("token", sa.Text),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(16), nullable=False, server_default="new"),
            sa.Column("message", sa.String(300)),
            sa.Column("last_sync_at", sa.DateTime(timezone=True)),
            sa.Column("last_result", sa.JSON),
        )
    cols = {c["name"] for c in sa.inspect(bind).get_columns("holdings")}
    if "stop_raw" not in cols:
        op.add_column("holdings", sa.Column("stop_raw", sa.Float))
    if "stop_set_on" not in cols:
        op.add_column("holdings", sa.Column("stop_set_on", sa.Date))


def downgrade() -> None:
    op.drop_column("holdings", "stop_set_on")
    op.drop_column("holdings", "stop_raw")
    op.drop_table("broker_links")
    op.drop_index("ix_portfolio_trades_portfolio_date", "portfolio_trades")
    op.drop_table("portfolio_trades")
