"""add event_ingests and events.ingest_id

Revision ID: b8f2c5a91d47
Revises: f3a1c9d2e4b7
Create Date: 2026-11-11 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8f2c5a91d47"
down_revision: Union[str, Sequence[str], None] = "f3a1c9d2e4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    `events.ingest_id` queda nullable: los eventos guardados antes de este cambio no tienen una
    ingesta que los identifique y se agrupan como la pseudo-ingesta `legacy` (docs/09 §102). Las
    filas viejas no se tocan.
    """
    op.create_table(
        "event_ingests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("archivo", sa.String(), nullable=False),
        sa.Column("ruta", sa.String(), nullable=False),
        sa.Column("ingerido_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eventos", sa.Integer(), nullable=False),
        sa.Column("eventos_leidos", sa.Integer(), nullable=False),
        sa.Column("eventos_existentes", sa.Integer(), nullable=False),
        sa.Column("desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fuentes", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ingest_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_events_ingest_id_event_ingests", "event_ingests", ["ingest_id"], ["id"]
        )


def downgrade() -> None:
    """Downgrade schema.

    El FK de `ingest_id` se va con la columna al reconstruir la tabla; declararlo aparte fallaria
    sin convencion de nombres (mismo criterio que la migracion del motor de ops).
    """
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_column("ingest_id")

    op.drop_table("event_ingests")
