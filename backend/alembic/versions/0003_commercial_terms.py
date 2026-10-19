"""Discount categories and separate production / delivery periods."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.add_column(
        "customers",
        sa.Column("discount_kind", sa.String(30), nullable=False, server_default="contract"),
    )
    op.add_column(
        "products", sa.Column("production_days", sa.Integer, nullable=False, server_default="0")
    )
    op.add_column(
        "products", sa.Column("delivery_days", sa.Integer, nullable=False, server_default="0")
    )
    op.execute("UPDATE products SET delivery_days = lead_days")


def downgrade():
    op.drop_column("products", "delivery_days")
    op.drop_column("products", "production_days")
    op.drop_column("customers", "discount_kind")
