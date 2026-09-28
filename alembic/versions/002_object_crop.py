"""Optional crop of a layer object («Культура» in object properties).

Revision ID: 002_object_crop
Revises: 001_initial
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_object_crop"
down_revision: Union[str, Sequence[str], None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive only: a nullable column, existing rows keep NULL.
    op.add_column("layer_objects", sa.Column("crop", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("layer_objects", "crop")
