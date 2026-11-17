"""financial_statements: balance sheet and income statement filings per symbol

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so the table may already exist
    if "financial_statements" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "financial_statements",
        sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), primary_key=True),
        sa.Column("published_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("period_end", sa.Date, nullable=True),
        sa.Column("fiscal_year_end", sa.Date, nullable=True),
        sa.Column("period_months", sa.Integer, nullable=True),
        sa.Column("audited", sa.Boolean, nullable=True),
        sa.Column("balance", sa.JSON, nullable=False),
        sa.Column("income", sa.JSON, nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_financial_statements_instrument_id", "financial_statements", ["instrument_id"]
    )


def downgrade() -> None:
    op.drop_table("financial_statements")
