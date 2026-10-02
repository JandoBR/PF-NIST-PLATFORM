"""normalize plan estado

Los planes pasan a tener un estado de *seguimiento* (docs/05 §4.4, docs/11): `pendiente`,
`en_progreso`, `hecho`. Antes la columna `estado` existia con el valor por defecto `abierto`
(sin uso); esta migracion de datos normaliza las filas existentes. No cambia el esquema.

Revision ID: 21178e83bca2
Revises: 0d33cddaac8d
Create Date: 2026-10-01 21:56:13.511230

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '21178e83bca2'
down_revision: Union[str, Sequence[str], None] = '0d33cddaac8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade data."""
    op.execute("UPDATE plans SET estado = 'pendiente' WHERE estado = 'abierto' OR estado = ''")


def downgrade() -> None:
    """Downgrade data."""
    op.execute("UPDATE plans SET estado = 'abierto' WHERE estado = 'pendiente'")
