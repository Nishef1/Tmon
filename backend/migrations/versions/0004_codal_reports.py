"""codal_reports and codal_report_cells: parsed Codal report bodies

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so these may already exist
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("codal_reports"):
        op.create_table(
            "codal_reports",
            sa.Column(
                "tracing_no",
                sa.BigInteger,
                sa.ForeignKey("codal_letters.tracing_no"),
                primary_key=True,
                autoincrement=False,
            ),
            sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
            sa.Column("letter_code", sa.String(16), index=True),
            sa.Column("period_end", sa.String(10), index=True),
            sa.Column("is_correction", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("subsidiary", sa.Text),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("format_signature", sa.String(16), nullable=False, index=True),
            sa.Column("n_tables", sa.Integer, nullable=False),
            sa.Column("n_cells", sa.Integer, nullable=False),
            sa.Column("raw_object_key", sa.Text),
            sa.Column("source_url", sa.Text),
            sa.Column("fetched_at", sa.DateTime(timezone=True)),
        )
    if not insp.has_table("codal_report_cells"):
        op.create_table(
            "codal_report_cells",
            sa.Column(
                "tracing_no",
                sa.BigInteger,
                sa.ForeignKey("codal_reports.tracing_no"),
                primary_key=True,
                autoincrement=False,
            ),
            sa.Column("table_index", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("row_index", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("col_index", sa.Integer, primary_key=True, autoincrement=False),
            sa.Column("table_title", sa.Text),
            sa.Column("row_label", sa.Text),
            sa.Column("col_header", sa.Text),
            sa.Column("text", sa.Text, nullable=False),
            sa.Column("value", sa.Float),
        )


def downgrade() -> None:
    op.drop_table("codal_report_cells")
    op.drop_table("codal_reports")
