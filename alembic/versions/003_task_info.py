"""Processing details of a task (scale the snapshot was processed at, window count).

Revision ID: 003_task_info
Revises: 002_object_crop
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_task_info"
down_revision: Union[str, Sequence[str], None] = "002_object_crop"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive only: a nullable JSON column, existing tasks keep NULL.
    op.add_column("processing_tasks", sa.Column("info", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("processing_tasks", "info")
