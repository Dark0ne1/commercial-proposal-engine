"""Initial schema: fixed table definitions, independent of future ORM changes."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("password", sa.String(200), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("details", sa.Text, nullable=False),
        sa.Column("discount", sa.Numeric(5, 2), nullable=False),
        sa.Column("payment_terms", sa.String(200), nullable=False),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sku", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("stock", sa.Numeric(14, 3), nullable=False),
        sa.Column("lead_days", sa.Integer, nullable=False),
    )
    op.create_table(
        "inquiries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("create_key", sa.String(100), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("confirmed_revision", sa.Integer),
        sa.Column("lock_version", sa.Integer, nullable=False),
    )
    op.create_table(
        "quote_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("inquiry_id", sa.String(36), sa.ForeignKey("inquiries.id"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("operation_key", sa.String(100), nullable=False, unique=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("inquiry_id", "revision"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("inquiry_id", sa.String(36), sa.ForeignKey("inquiries.id"), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_inquiry_id", "audit_events", ["inquiry_id"])


def downgrade():
    for table in (
        "audit_events",
        "quote_versions",
        "inquiries",
        "products",
        "customers",
        "sessions",
        "users",
    ):
        op.drop_table(table)
