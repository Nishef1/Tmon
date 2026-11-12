"""sector_names: exchange industry-group code -> name

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so it may already exist
    if sa.inspect(op.get_bind()).has_table("sector_names"):
        return
    op.create_table(
        "sector_names",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("sector_names")
