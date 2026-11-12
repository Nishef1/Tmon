"""Indexes on the date column of the three large daily tables

Every "all symbols on one day" query (screener, market, ranking) scanned the whole table because
the primary key leads with instrument_id: 12 s for the screener on 2.9 million price rows.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABLES = ("prices_daily", "client_types_daily", "features")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table in TABLES:
        name = f"ix_{table}_date"
        if not any(i["name"] == name for i in insp.get_indexes(table)):
            op.create_index(name, table, ["date"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_date", table_name=table)
