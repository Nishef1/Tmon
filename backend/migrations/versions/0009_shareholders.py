"""shareholders: latest major-shareholder list per instrument

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the table may already exist
    if sa.inspect(op.get_bind()).has_table("shareholders"):
        return
    op.create_table(
        "shareholders",
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), primary_key=True),
        sa.Column("holder_key", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("shares", sa.BigInteger),
        sa.Column("percent", sa.Float),
        sa.Column("change_amount", sa.BigInteger),
        sa.Column("source_url", sa.Text),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("shareholders")
