"""CRI-ID-05 — Mejora continua (docs/03 §2).

Mixto, y a proposito: lo documental es el ciclo de mejora (`doc.claim(process_defined)` con
`contenido.proceso` de mejora/lecciones aprendidas, mas `metricas`/`ajustes`), y lo operativo es el
ejercicio observado (`log.pattern(restore_exercise_run)`), que es lo unico que permite declarar
`ID.IM-02` ("mejoras a partir de pruebas y ejercicios") sin creerle solo al documento.

No exige ventana completa para la via documental: igual que CRI-RC-02, sin eventos se evalua lo
documental con tope 75.

`ID.IM-04` ("los planes de respuesta y otros planes se establecen, comunican, mantienen y mejoran")
entra por `contenido.planes_actualizados`. Es condicion del 100: un ciclo de mejora que mide y
ajusta pero no toca los planes no evidencia esta subcategoria, y era el motivo por el que la
Oleada A la dejo fuera (docs/09 §72).
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    by_type,
    doc_claims,
    found,
    latest_pattern,
    merged_content,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-05"
CRITERION_VERSION = 2


def _es_de_mejora(claim: EvidenceInstance) -> bool:
    contenido = claim.value.get("contenido") or {}
    proceso = str(contenido.get("proceso", "")).lower()
    return bool(
        any(
            palabra in proceso
            for palabra in ("mejora", "leccion", "lección", "lecciones", "retrospectiva", "madurez")
        )
        or contenido.get("planes_actualizados")
    )


def _ejercicio(evidence: list[EvidenceInstance]) -> EvidenceInstance | None:
    ventana = by_type(evidence, "log.window")
    if not ventana or not ventana[0].value["completo"]:
        return None
    return latest_pattern(evidence, "restore_exercise_run")


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "process_defined")
    candidatos = [c for c in claims if _es_de_mejora(c)]
    encontradas = found(candidatos)
    contenido, aportantes = merged_content(encontradas)
    ejercicio = _ejercicio(evidence)
    ids = [c.id for c in aportantes or encontradas]

    if not encontradas:
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

    con_seguimiento = bool(contenido.get("metricas") or contenido.get("ajustes"))
    planes = bool(contenido.get("planes_actualizados"))

    if con_seguimiento and ejercicio is not None and planes:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            "Ciclo de mejora con metricas/ajustes, un ejercicio observado que lo alimenta y planes"
            " que se mantienen con lo aprendido.",
            [*ids, ejercicio.id],
        )
    if con_seguimiento and ejercicio is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Ciclo de mejora con metricas/ajustes y un ejercicio observado, pero no se declara que"
            " los planes se actualicen con lo aprendido (ID.IM-04).",
            [*ids, ejercicio.id],
        )
    if con_seguimiento:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Ciclo de mejora documentado con metricas/ajustes, sin ejercicios observados.",
            ids,
        )
    if ejercicio is not None:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            "Proceso de mejora documentado y ejercicio observado, sin metricas ni ajustes"
            " declarados.",
            [*ids, ejercicio.id],
        )
    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        50,
        "Mejora continua descrita de forma generica, sin metricas, ajustes ni ejercicios.",
        ids,
    )
