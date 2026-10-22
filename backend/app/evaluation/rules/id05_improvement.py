"""CRI-ID-05 — Mejora continua (docs/03 §2).

Mixto, y a proposito: lo documental es el ciclo de mejora (`doc.claim(process_defined)` con
`contenido.proceso` de mejora/lecciones aprendidas, mas `metricas`/`ajustes`), y lo operativo es el
ejercicio observado (`log.pattern(restore_exercise_run)`), que es lo unico que permite declarar
`ID.IM-02` ("mejoras a partir de pruebas y ejercicios") sin creerle solo al documento.

No exige ventana completa para la via documental: igual que CRI-RC-02, sin eventos se evalua lo
documental con tope 75.
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    best_found,
    by_type,
    doc_claims,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-05"
CRITERION_VERSION = 1


def _es_de_mejora(claim: EvidenceInstance) -> bool:
    proceso = str((claim.value.get("contenido") or {}).get("proceso", "")).lower()
    return any(
        palabra in proceso
        for palabra in ("mejora", "leccion", "lección", "lecciones", "retrospectiva", "madurez")
    )


def _ejercicio(evidence: list[EvidenceInstance]) -> EvidenceInstance | None:
    ventana = by_type(evidence, "log.window")
    if not ventana or not ventana[0].value["completo"]:
        return None
    for item in by_type(evidence, "log.pattern"):
        if item.value["patron"] == "restore_exercise_run":
            return item
    return None


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "process_defined")
    candidatos = [c for c in claims if _es_de_mejora(c)]
    mejor = best_found(candidatos)
    ejercicio = _ejercicio(evidence)

    if mejor is None:
        if ejercicio is not None:
            return result(
                CRITERION_ID,
                Estado.EVALUADO,
                50,
                "Ejercicio de seguridad observado, sin un ciclo de mejora documentado que recoja"
                " sus resultados.",
                [ejercicio.id],
            )
        if claims:
            return silencio_documental(
                CRITERION_ID,
                "Los documentos analizados no declaran un proceso de mejora continua ni de"
                " lecciones aprendidas.",
                [c.id for c in claims],
            )
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre mejora continua.",
        )

    contenido = mejor.value.get("contenido") or {}
    con_seguimiento = bool(contenido.get("metricas") or contenido.get("ajustes"))

    if con_seguimiento and ejercicio is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Ciclo de mejora con metricas/ajustes y un ejercicio observado que lo alimenta.",
            [mejor.id, ejercicio.id],
        )
    if con_seguimiento:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Ciclo de mejora documentado con metricas/ajustes, sin ejercicios observados.",
            [mejor.id],
        )
    if ejercicio is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Proceso de mejora documentado y ejercicio observado, sin metricas ni ajustes"
            " declarados.",
            [mejor.id, ejercicio.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Mejora continua descrita de forma generica, sin metricas, ajustes ni ejercicios.",
        [mejor.id],
    )
