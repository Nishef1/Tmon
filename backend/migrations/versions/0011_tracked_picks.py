"""tracked_picks: symbols the user bought, with the forecast frozen that day

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the table may already exist
    if "tracked_picks" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "tracked_picks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
        sa.Column("entered_on", sa.Date, nullable=False),
        sa.Column("paid_price", sa.Float, nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tracked_picks")
