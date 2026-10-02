"""add previous_assessment_id to assessments

Revision ID: 9f9593a6de1c
Revises: 21178e83bca2
Create Date: 2026-10-01 22:07:41.414568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f9593a6de1c'
down_revision: Union[str, Sequence[str], None] = '21178e83bca2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('previous_assessment_id', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_assessments_previous_assessment_id_assessments',
            'assessments',
            ['previous_assessment_id'],
            ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_assessments_previous_assessment_id_assessments', type_='foreignkey'
        )
        batch_op.drop_column('previous_assessment_id')
