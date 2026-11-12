"""signals.hit: the label's own y at resolution (relative target, OPEN_QUESTIONS 67)

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the column may already exist
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("signals")}
    if "hit" not in cols:
        with op.batch_alter_table("signals") as b:
            b.add_column(sa.Column("hit", sa.Boolean, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("signals") as b:
        b.drop_column("hit")
