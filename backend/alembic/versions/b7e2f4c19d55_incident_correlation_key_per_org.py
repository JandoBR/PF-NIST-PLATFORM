"""incident correlation_key unique per organization

Revision ID: b7e2f4c19d55
Revises: a9d4e6b1c280
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e2f4c19d55'
down_revision: Union[str, Sequence[str], None] = 'a9d4e6b1c280'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# La restriccion original (277dd5fd4475) no tiene nombre. Postgres la llama
# `incidents_correlation_key_key`; en SQLite se le da nombre al reflejar la tabla.
_NEW = 'uq_incidents_org_correlation_key'
_OLD_POSTGRES = 'incidents_correlation_key_key'
_OLD_SQLITE = 'uq_incidents_correlation_key'
_SQLITE_NAMING = {'uq': 'uq_%(table_name)s_%(column_0_name)s'}


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('incidents', naming_convention=_SQLITE_NAMING) as batch_op:
            batch_op.drop_constraint(_OLD_SQLITE, type_='unique')
            batch_op.create_unique_constraint(_NEW, ['org_id', 'correlation_key'])
        return
    op.drop_constraint(_OLD_POSTGRES, 'incidents', type_='unique')
    op.create_unique_constraint(_NEW, 'incidents', ['org_id', 'correlation_key'])


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('incidents', naming_convention=_SQLITE_NAMING) as batch_op:
            batch_op.drop_constraint(_NEW, type_='unique')
            batch_op.create_unique_constraint(_OLD_SQLITE, ['correlation_key'])
        return
    op.drop_constraint(_NEW, 'incidents', type_='unique')
    op.create_unique_constraint(_OLD_POSTGRES, 'incidents', ['correlation_key'])
