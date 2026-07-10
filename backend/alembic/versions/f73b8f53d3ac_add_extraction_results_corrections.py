"""add extraction_results.corrections

Revision ID: f73b8f53d3ac
Revises: 0002_form_fill_runs
Create Date: 2026-07-10 16:18:48.309303

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f73b8f53d3ac'
down_revision: Union[str, None] = '0002_form_fill_runs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('extraction_results', sa.Column('corrections', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('extraction_results', 'corrections')
