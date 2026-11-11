"""codal_letters and Codal provenance on corporate_events

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so these may already exist
    insp = _inspector()
    if not insp.has_table("codal_letters"):
        op.create_table(
            "codal_letters",
            sa.Column("tracing_no", sa.BigInteger, primary_key=True, autoincrement=False),
            sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
            sa.Column("symbol", sa.String(64), nullable=False, index=True),
            sa.Column("company_name", sa.Text),
            sa.Column("letter_code", sa.String(16), index=True),
            sa.Column("title", sa.Text, nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True)),
            sa.Column("published_at", sa.DateTime(timezone=True), index=True),
            sa.Column("url", sa.Text),
            sa.Column("has_html", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("has_excel", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("has_pdf", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("under_supervision", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("source_url", sa.Text),
            sa.Column("fetched_at", sa.DateTime(timezone=True)),
        )
    cols = {c["name"] for c in insp.get_columns("corporate_events")}
    with op.batch_alter_table("corporate_events") as batch:
        if "tracing_no" not in cols:
            batch.add_column(sa.Column("tracing_no", sa.BigInteger))
            batch.create_unique_constraint("uq_corporate_events_tracing_no", ["tracing_no"])
        if "stage" not in cols:
            batch.add_column(sa.Column("stage", sa.String(32)))
        if "title" not in cols:
            batch.add_column(sa.Column("title", sa.Text))


def downgrade() -> None:
    with op.batch_alter_table("corporate_events") as batch:
        batch.drop_constraint("uq_corporate_events_tracing_no", type_="unique")
        batch.drop_column("title")
        batch.drop_column("stage")
        batch.drop_column("tracing_no")
    op.drop_table("codal_letters")
