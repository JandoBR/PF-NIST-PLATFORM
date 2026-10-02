"""add reproducibility to assessments

Revision ID: c41a7d2e9b10
Revises: 9f9593a6de1c
Create Date: 2026-10-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41a7d2e9b10'
down_revision: Union[str, Sequence[str], None] = '9f9593a6de1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reproducibility', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.drop_column('reproducibility')
