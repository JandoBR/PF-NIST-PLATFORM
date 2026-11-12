"""CRI-PR-02 — Backups configurados y protegidos (docs/03 §3).

Tecnico (`tf.backup.config`) mas politica documentada (`doc.claim(backup_policy)`): el 100 exige que
la retencion configurada cumpla la retencion de la politica. Sin politica legible, el tope es 75.
"""

from __future__ import annotations

import re

from app.ai.numbers import normalizar_cantidades
from app.ai.quotes import normalize
from app.evaluation.rules._common import (
    best_found_with,
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

_RETENCION_RE = re.compile(r"(\d+)\s*([a-z]*)")
#: Prefijo de la unidad -> dias. Sin unidad reconocida se asumen dias.
_UNIDADES_DIAS = (
    ("sem", 7),
    ("week", 7),
    ("mes", 30),
    ("month", 30),
    ("ano", 365),
    ("year", 365),
)


def retencion_politica_dias(claim: EvidenceInstance) -> int | None:
    """Dias de `contenido.retencion` (texto libre: "7 dias", "7d", "2 semanas", "noventa dias").
    Meses y años son aproximados (30 y 365 dias). Las cantidades escritas con palabras se
    normalizan antes de leer el numero (docs/09 §106)."""

    contenido = claim.value.get("contenido") or {}
    texto = normalize(normalizar_cantidades(str(contenido.get("retencion") or "")))
    coincidencia = _RETENCION_RE.search(texto)
    if coincidencia is None:
        return None
    cantidad, unidad = int(coincidencia.group(1)), coincidencia.group(2)
    factor = next((dias for prefijo, dias in _UNIDADES_DIAS if unidad.startswith(prefijo)), 1)
    return cantidad * factor


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
        # Ninguna base con backups: ausencia explicita (0). Si otras si los tienen es parcial (25).
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0 if len(disabled) == len(resolved) else 25,
            "Backups deshabilitados explicitamente en: "
            + ", ".join(e.subject_ref for e in disabled)
            + ".",
            [e.id for e in resolved],
        )

    peor_retencion = min(e.value["retencion_dias"] for e in resolved)
    politica = best_found_with(doc_claims(evidence, "backup_policy"), "retencion")
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
