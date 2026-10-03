"""add motivo_cierre to incidents

Revision ID: a9d4e6b1c280
Revises: f1b6d2a85c37
Create Date: 2026-10-02 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d4e6b1c280'
down_revision: Union[str, Sequence[str], None] = 'f1b6d2a85c37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('motivo_cierre', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('incidents', schema=None) as batch_op:
        batch_op.drop_column('motivo_cierre')
