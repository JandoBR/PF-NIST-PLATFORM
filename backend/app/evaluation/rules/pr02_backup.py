"""CRI-PR-02 — Backups configurados y protegidos (docs/03 §3).

Tecnico (`tf.backup.config`) mas politica documentada (`doc.claim(backup_policy)`): el 100 exige que
la retencion configurada cumpla la retencion de la politica. Sin politica legible, el tope es 75.
"""

from __future__ import annotations

import re

from app.evaluation.rules._common import (
    best_found,
    by_type,
    doc_claims,
    noting_unresolved,
    result,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-02"
CRITERION_VERSION = 1
RETENCION_MINIMA_DIAS = 7

_DIAS_RE = re.compile(r"(\d+)")


def retencion_politica_dias(claim: EvidenceInstance) -> int | None:
    """Extrae los dias de `contenido.retencion` (texto libre: "7 dias", "7d", "1 mes")."""

    contenido = claim.value.get("contenido") or {}
    coincidencia = _DIAS_RE.search(str(contenido.get("retencion") or ""))
    return int(coincidencia.group(1)) if coincidencia else None


def _rds_sin_cifrado(evidence: list[EvidenceInstance], recursos: list[str]) -> list[str]:
    """Recursos cuya instancia no tiene cifrado confirmado (`enabled`): sus backups heredan el
    cifrado del almacenamiento, asi que sin el el 100 no se justifica (docs/03 §3)."""

    estado = {
        e.subject_ref: e.value["estado"]
        for e in by_type(evidence, "tf.encryption.config")
        if e.subject_type == "aws_db_instance"
    }
    return [ref for ref in recursos if estado.get(ref) != "enabled"]


@noting_unresolved({"backup_retention_period"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    relevant = by_type(evidence, "tf.backup.config")
    if not relevant:
        return result(
            CRITERION_ID,
            Estado.NO_APLICABLE,
            None,
            "Sin bases de datos administradas en el alcance.",
        )

    resolved = [e for e in relevant if e.value["retencion_dias"] is not None]
    unknown = [e for e in relevant if e.value["retencion_dias"] is None]

    if not resolved:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Retencion de backups desconocida para todos los recursos.",
            [e.id for e in unknown],
        )

    disabled = [e for e in resolved if e.value["retencion_dias"] == 0]
    if disabled:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            25,
            "Backups deshabilitados explicitamente en: "
            + ", ".join(e.subject_ref for e in disabled)
            + ".",
            [e.id for e in resolved],
        )

    peor_retencion = min(e.value["retencion_dias"] for e in resolved)
    politica = best_found(doc_claims(evidence, "backup_policy"))
    politica_dias = retencion_politica_dias(politica) if politica else None
    ids_tf = [e.id for e in resolved]

    if politica_dias is not None:
        if peor_retencion >= politica_dias:
            sin_cifrado = _rds_sin_cifrado(evidence, [e.subject_ref for e in resolved])
            if sin_cifrado:
                return result(
                    CRITERION_ID,
                    Estado.EVALUADO,
                    75,
                    f"Retencion configurada ({peor_retencion} dias) cumple la politica documentada"
                    f" ({politica_dias} dias), pero el cifrado de los backups no esta confirmado"
                    " en: " + ", ".join(sin_cifrado) + ". Puntaje maximo 75.",
                    [politica.id, *ids_tf],
                )
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                100,
                f"Retencion configurada ({peor_retencion} dias) cumple la politica documentada"
                f" ({politica_dias} dias).",
                [politica.id, *ids_tf],
            )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            f"Retencion minima {peor_retencion} dias por debajo de la politica documentada"
            f" ({politica_dias} dias).",
            [politica.id, *ids_tf],
        )

    if peor_retencion >= RETENCION_MINIMA_DIAS:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            f"Retencion minima observada {peor_retencion} dias (>= {RETENCION_MINIMA_DIAS}), sin"
            " politica documentada: puntaje maximo 75.",
            ids_tf,
        )

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        f"Backups habilitados con retencion minima {peor_retencion} dias (< {RETENCION_MINIMA_DIAS}"
        " y sin politica que la respalde).",
        ids_tf,
    )
