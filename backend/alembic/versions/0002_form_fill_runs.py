"""form_fill_runs: browser-automation run tracking

Revision ID: 0002_form_fill_runs
Revises: 0001_initial
Create Date: 2026-07-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_form_fill_runs"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "form_fill_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("form_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_form_fill_runs_application_id", "form_fill_runs", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_form_fill_runs_application_id", table_name="form_fill_runs")
    op.drop_table("form_fill_runs")
