"""incident correlation_key unique per organization and scope

Revision ID: f3a1c9d2e4b7
Revises: b7e2f4c19d55
Create Date: 2026-10-25 12:00:00.000000

La clave de correlacion sale del recurso y la hora del evento, no del entorno. Con la restriccion
anterior `(org_id, correlation_key)`, el mismo host y la misma hora en produccion y staging se
fusionaban en un solo incidente. docs/08 §3 define los incidentes por org+scope, asi que la
identidad correcta es `(org_id, scope, correlation_key)`.

Es solo esquema: los eventos de ejemplo son JSONL y no guardan incidentes. Las filas existentes
siguen siendo validas (agregar `scope` a la clave relaja la unicidad); una fila ya fusionada no se
puede separar retroactivamente.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f3a1c9d2e4b7'
down_revision: Union[str, Sequence[str], None] = 'b7e2f4c19d55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = 'uq_incidents_org_correlation_key'
_NEW = 'uq_incidents_org_scope_correlation_key'
_SQLITE_NAMING = {'uq': 'uq_%(table_name)s_%(column_0_name)s'}


def upgrade() -> None:
    """Upgrade schema."""
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('incidents', naming_convention=_SQLITE_NAMING) as batch_op:
            batch_op.drop_constraint(_OLD, type_='unique')
            batch_op.create_unique_constraint(
                _NEW, ['org_id', 'scope', 'correlation_key']
            )
        return
    op.drop_constraint(_OLD, 'incidents', type_='unique')
    op.create_unique_constraint(_NEW, 'incidents', ['org_id', 'scope', 'correlation_key'])


def downgrade() -> None:
    """Downgrade schema.

    Falla si hay dos incidentes del mismo org y correlation_key en scopes distintos: volver a la
    restriccion vieja exigiria fusionarlos, y eso perderia informacion.
    """
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('incidents', naming_convention=_SQLITE_NAMING) as batch_op:
            batch_op.drop_constraint(_NEW, type_='unique')
            batch_op.create_unique_constraint(_OLD, ['org_id', 'correlation_key'])
        return
    op.drop_constraint(_NEW, 'incidents', type_='unique')
    op.create_unique_constraint(_OLD, 'incidents', ['org_id', 'correlation_key'])
