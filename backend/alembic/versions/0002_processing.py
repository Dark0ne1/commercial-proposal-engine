"""Document provenance and durable agent runs."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.add_column("inquiries", sa.Column("source_info", sa.JSON, nullable=True))
    op.add_column("inquiries", sa.Column("extracted_text", sa.Text, nullable=True))
    op.create_table(
        "processing_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("inquiry_id", sa.String(36), sa.ForeignKey("inquiries.id"), nullable=False),
        sa.Column("operation_key", sa.String(100), unique=True, nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("clarification", sa.Text, nullable=False),
        sa.Column("base_revision", sa.Integer, nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("extraction", sa.JSON),
        sa.Column("result", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_processing_runs_inquiry_id", "processing_runs", ["inquiry_id"])
    op.create_table(
        "agent_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("processing_runs.id"), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("arguments", sa.JSON, nullable=False),
        sa.Column("output", sa.JSON),
        sa.Column("error", sa.Text),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("usage", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_calls_run_id", "agent_calls", ["run_id"])


def downgrade():
    op.drop_table("agent_calls")
    op.drop_table("processing_runs")
    op.drop_column("inquiries", "extracted_text")
    op.drop_column("inquiries", "source_info")
