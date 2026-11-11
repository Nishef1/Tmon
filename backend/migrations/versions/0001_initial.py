"""initial schema + TimescaleDB hypertables

Revision ID: 0001
Revises:
"""

from alembic import op

from tmon.storage.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# table -> (time column, chunk interval)
HYPERTABLES = {
    "prices_daily": ("date", "1 year"),
    "client_types_daily": ("date", "1 year"),
    "features": ("date", "1 year"),
    "intraday_snapshots": ("ts", "7 days"),
    "order_book_snapshots": ("ts", "7 days"),
}


def upgrade() -> None:
    bind = op.get_bind()
    # Baseline only: later migrations must be explicit operations, never create_all.
    Base.metadata.create_all(bind)
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    for table, (column, interval) in HYPERTABLES.items():
        op.execute(
            f"SELECT create_hypertable('{table}', '{column}', "
            f"chunk_time_interval => INTERVAL '{interval}', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        )


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
