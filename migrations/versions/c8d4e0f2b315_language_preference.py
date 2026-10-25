"""Add user language preference.
Revision ID: c8d4e0f2b315
Revises: b7c3d9e1a204
"""
from alembic import op
import sqlalchemy as sa
revision = "c8d4e0f2b315"
down_revision = "b7c3d9e1a204"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("users", sa.Column("language", sa.String(12), nullable=False, server_default="en"))

def downgrade():
    op.drop_column("users", "language")
