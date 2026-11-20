"""shares_history and shareholders_history: monthly dated share counts and major holders

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _prov() -> list[sa.Column]:
    return [
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the tables may exist
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "shares_history" not in have:
        op.create_table(
            "shares_history",
            sa.Column(
                "instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), primary_key=True
            ),
            sa.Column("date", sa.Date, primary_key=True),
            sa.Column("shares", sa.Float, nullable=True),
            sa.Column("base_volume", sa.Float, nullable=True),
            *_prov(),
        )
    if "shareholders_history" not in have:
        op.create_table(
            "shareholders_history",
            sa.Column(
                "instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), primary_key=True
            ),
            sa.Column("date", sa.Date, primary_key=True),
            sa.Column("holder_key", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("shares", sa.Float, nullable=True),
            sa.Column("percent", sa.Float, nullable=True),
            *_prov(),
        )


def downgrade() -> None:
    op.drop_table("shareholders_history")
    op.drop_table("shares_history")
