"""add ai_results

Revision ID: c7a1e5d904b3
Revises: b8f2c5a91d47
Create Date: 2026-11-11 18:00:00.000000

Cache persistente de resultados de IA por organizacion (docs/05 §7). La cache en disco vivia en
cada contenedor (`/app/backend/.cache`), no estaba montada y se perdia al recrear api/workers;
esto la reemplaza en el camino de produccion. La unique es la clave completa: dos workers que
calculan el mismo insumo a la vez no duplican la fila (el segundo conserva la primera respuesta).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a1e5d904b3"
down_revision: Union[str, Sequence[str], None] = "b8f2c5a91d47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("params_hash", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("input_sha256", sa.String(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "kind",
            "model",
            "base_url",
            "params_hash",
            "prompt_version",
            "input_sha256",
            name="uq_ai_results_key",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("ai_results")
