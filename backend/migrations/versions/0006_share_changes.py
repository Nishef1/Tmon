"""share_changes: TSETMC share-count events (R0 data completion)

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so it may already exist
    if sa.inspect(op.get_bind()).has_table("share_changes"):
        return
    op.create_table(
        "share_changes",
        sa.Column("idn", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("ins_code", sa.String(32), nullable=False, index=True),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("shares_new", sa.BigInteger, nullable=False),
        sa.Column("shares_old", sa.BigInteger, nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("share_changes")
