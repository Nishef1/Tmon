"""fund_nav, news_raw and news_events (C5/T7)

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def _provenance() -> list[sa.Column]:
    return [
        sa.Column("source_url", sa.Text),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    # 0001 builds the whole current metadata on a fresh database, so these may already exist
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("fund_nav"):
        op.create_table(
            "fund_nav",
            sa.Column("reg_no", sa.String(16), primary_key=True),
            sa.Column("date", sa.Date, primary_key=True),
            sa.Column("name", sa.String(256)),
            sa.Column("ins_code", sa.String(32), index=True),
            sa.Column("instrument_id", sa.Integer, sa.ForeignKey("instruments.id"), index=True),
            sa.Column("fund_type", sa.Integer),
            sa.Column("type_of_invest", sa.String(32)),
            sa.Column("cancel_nav", sa.Float),
            sa.Column("issue_nav", sa.Float),
            sa.Column("statistical_nav", sa.Float),
            sa.Column("net_asset", sa.Float),
            *_provenance(),
        )
    if not insp.has_table("news_raw"):
        op.create_table(
            "news_raw",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("source", sa.String(32), nullable=False, index=True),
            sa.Column("url", sa.Text, nullable=False, unique=True),
            sa.Column("title", sa.Text, nullable=False),
            sa.Column("summary", sa.Text),
            sa.Column("published_at", sa.DateTime(timezone=True), index=True),
            sa.Column("title_norm", sa.Text, nullable=False),
            sa.Column("cluster_id", sa.Integer, index=True),
            *_provenance(),
        )
    if not insp.has_table("news_events"):
        op.create_table(
            "news_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "news_id", sa.Integer, sa.ForeignKey("news_raw.id"), nullable=False, unique=True
            ),
            sa.Column("event_type", sa.String(32), nullable=False, index=True),
            sa.Column("symbols", JSON, nullable=False),
            sa.Column("sectors", JSON, nullable=False),
            sa.Column("direction", sa.Integer, nullable=False),
            sa.Column("magnitude", sa.Integer, nullable=False),
            sa.Column("confidence", sa.Float, nullable=False),
            sa.Column("effective_from", sa.Date),
            sa.Column("horizon", sa.String(8)),
            sa.Column("is_official", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("summary_fa", sa.Text),
            sa.Column("model", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for name in ("news_events", "news_raw", "fund_nav"):
        if insp.has_table(name):
            op.drop_table(name)
