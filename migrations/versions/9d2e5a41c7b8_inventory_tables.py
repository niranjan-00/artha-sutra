"""Add inventory tables: products, batches, stock movements, stock alerts.

Revision ID: 9d2e5a41c7b8
Revises: 4c1a9b7d2f03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "9d2e5a41c7b8"
down_revision = "4c1a9b7d2f03"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    if "products" not in existing:
        op.create_table(
            "products",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id", ondelete="SET NULL")),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("sku", sa.String(60)),
            sa.Column("category", sa.String(80), nullable=False, server_default="General"),
            sa.Column("unit", sa.String(20), nullable=False, server_default="units"),
            sa.Column("purchase_price_paise", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("selling_price_paise", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("min_stock", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lead_time_days", sa.Integer()),
            sa.Column("tracks_expiry", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("business_id", "sku", name="uq_products_business_sku"),
        )
        op.create_index("ix_products_business_id", "products", ["business_id"])
        op.create_index("ix_products_supplier_id", "products", ["supplier_id"])
        op.create_index("ix_products_name", "products", ["name"])
        op.create_index("ix_products_status", "products", ["status"])
    if "product_batches" not in existing:
        op.create_table(
            "product_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("batch_number", sa.String(60), nullable=False, server_default="UNBATCHED"),
            sa.Column("expiry_date", sa.Date()),
            sa.Column("unit_cost_paise", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("product_id", "batch_number", "expiry_date", name="uq_batch_identity"),
        )
        op.create_index("ix_product_batches_business_id", "product_batches", ["business_id"])
        op.create_index("ix_product_batches_product_id", "product_batches", ["product_id"])
        op.create_index("ix_product_batches_expiry_date", "product_batches", ["expiry_date"])
    if "stock_movements" not in existing:
        op.create_table(
            "stock_movements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("product_batches.id", ondelete="SET NULL")),
            sa.Column("movement_type", sa.String(20), nullable=False),
            sa.Column("quantity_change", sa.Integer(), nullable=False),
            sa.Column("unit_cost_paise", sa.BigInteger()),
            sa.Column("movement_date", sa.Date(), nullable=False),
            sa.Column("notes", sa.String(300)),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for col in ("business_id", "product_id", "batch_id", "movement_type", "movement_date"):
            op.create_index(f"ix_stock_movements_{col}", "stock_movements", [col])
    if "stock_alerts" not in existing:
        op.create_table(
            "stock_alerts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("product_batches.id", ondelete="CASCADE")),
            sa.Column("alert_type", sa.String(20), nullable=False),
            sa.Column("level", sa.String(20), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("message", sa.String(500), nullable=False),
            sa.Column("is_acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("acknowledged_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("resolved_at", sa.DateTime()),
        )
        for col in ("business_id", "product_id", "batch_id", "resolved_at"):
            op.create_index(f"ix_stock_alerts_{col}", "stock_alerts", [col])


def downgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    for table in ("stock_alerts", "stock_movements", "product_batches", "products"):
        if table in existing:
            op.drop_table(table)
