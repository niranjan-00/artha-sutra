"""Add GST tracker records.
Revision ID: b7c3d9e1a204
Revises: 9d2e5a41c7b8
"""
from alembic import op
import sqlalchemy as sa
revision = "b7c3d9e1a204"
down_revision = "9d2e5a41c7b8"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "gst_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filing_period", sa.String(40), nullable=False),
        sa.Column("record_type", sa.String(40), nullable=False, server_default="GST filing"),
        sa.Column("due_date", sa.Date()),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="upcoming"),
        sa.Column("reference", sa.String(120)),
        sa.Column("notes", sa.String(500)),
        sa.Column("deadline_source", sa.String(200), nullable=False, server_default="Owner-entered deadline; verify against the applicable official GST notice."),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_gst_records_business_id", "gst_records", ["business_id"])
    op.create_index("ix_gst_records_due_date", "gst_records", ["due_date"])

def downgrade():
    op.drop_index("ix_gst_records_due_date", table_name="gst_records")
    op.drop_index("ix_gst_records_business_id", table_name="gst_records")
    op.drop_table("gst_records")
