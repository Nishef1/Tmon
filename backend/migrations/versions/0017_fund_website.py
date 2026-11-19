"""fund_nav: the fund's own website and its manager (fipiran)

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

COLUMNS = ("website", "manager")


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the columns may exist
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("fund_nav")}
    with op.batch_alter_table("fund_nav") as batch:
        for name in COLUMNS:
            if name not in have:
                batch.add_column(sa.Column(name, sa.String(256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fund_nav") as batch:
        for name in COLUMNS:
            batch.drop_column(name)
