"""portfolios, holdings, portfolio_alerts, portfolio_briefings: separate user portfolios with
live alerts and pre-open briefings

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _portfolio_fk() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "portfolio_id", sa.Integer, sa.ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so tables may already exist
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "portfolios" not in existing:
        op.create_table(
            "portfolios",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("owner", sa.String(120)),
            sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("cash", sa.Float, nullable=False, server_default="0"),
            sa.Column("settings", sa.JSON, nullable=False),
            sa.Column("channels", sa.JSON, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "holdings" not in existing:
        op.create_table(
            "holdings",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            _portfolio_fk(),
            sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
            sa.Column("shares", sa.Float, nullable=False),
            sa.Column("avg_price", sa.Float, nullable=False),
            sa.Column("bought_on", sa.Date),
            sa.Column("stop_price", sa.Float),
            sa.Column("note", sa.String(300)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("portfolio_id", "instrument_id"),
        )
    if "portfolio_alerts" not in existing:
        op.create_table(
            "portfolio_alerts",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            _portfolio_fk(),
            sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id")),
            sa.Column("kind", sa.String(32), index=True),
            sa.Column("severity", sa.Integer, nullable=False),
            sa.Column("title", sa.Text, nullable=False),
            sa.Column("body", sa.Text, nullable=False),
            sa.Column("data", sa.JSON, nullable=False),
            sa.Column("dedupe_key", sa.String(200), index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), index=True),
            sa.Column("delivered", sa.JSON, nullable=False),
            sa.Column("answer", sa.String(16)),
            sa.Column("answered_at", sa.DateTime(timezone=True)),
        )
        op.create_index(
            "ix_portfolio_alerts_portfolio_created",
            "portfolio_alerts",
            ["portfolio_id", "created_at"],
        )
    if "portfolio_briefings" not in existing:
        op.create_table(
            "portfolio_briefings",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            _portfolio_fk(),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), index=True),
            sa.Column("method", sa.String(64), nullable=False),
            sa.Column("doc", sa.JSON, nullable=False),
        )


def downgrade() -> None:
    for t in ("portfolio_briefings", "portfolio_alerts", "holdings", "portfolios"):
        op.drop_table(t)
