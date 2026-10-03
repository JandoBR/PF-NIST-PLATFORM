"""add fuentes to log_patterns

Revision ID: e7a1c3d49b52
Revises: d52e8b7f1a43
Create Date: 2026-10-02 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a1c3d49b52'
down_revision: Union[str, Sequence[str], None] = 'd52e8b7f1a43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('log_patterns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fuentes', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('log_patterns', schema=None) as batch_op:
        batch_op.drop_column('fuentes')
