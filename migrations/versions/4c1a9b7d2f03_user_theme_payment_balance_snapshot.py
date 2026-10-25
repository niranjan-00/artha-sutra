"""Add persisted appearance and payment balance snapshots.

Revision ID: 4c1a9b7d2f03
Revises: f7a969f4315a
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "4c1a9b7d2f03"
down_revision = "f7a969f4315a"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    users = {column["name"] for column in inspect(bind).get_columns("users")}
    payments = {column["name"] for column in inspect(bind).get_columns("payments")}
    if "theme" not in users:
        op.add_column("users", sa.Column("theme", sa.String(length=12), nullable=False, server_default="light"))
    if "balance_after_paise" not in payments:
        op.add_column("payments", sa.Column("balance_after_paise", sa.BigInteger(), nullable=True))


def downgrade():
    bind = op.get_bind()
    payments = {column["name"] for column in inspect(bind).get_columns("payments")}
    users = {column["name"] for column in inspect(bind).get_columns("users")}
    if "balance_after_paise" in payments:
        op.drop_column("payments", "balance_after_paise")
    if "theme" in users:
        op.drop_column("users", "theme")
