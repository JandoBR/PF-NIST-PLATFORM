"""CRI-PR-01 — Cifrado de datos en reposo y en transito (PR.DS-01, PR.DS-02; docs/03 §3).

La observacion tecnica prevalece (D7): cualquier recurso `disabled` hace caer el puntaje aunque
otros esten `enabled`. Los recursos `unknown` no bloquean el calculo de los resueltos, pero quedan
registrados como limitacion.

**El transito es una compuerta sobre el 100, no una rama aparte.** El dato en reposo y el dato en
viaje son las dos mitades del mismo control (`PR.DS-01` y `PR.DS-02`), pero no son simetricas: un
fallo en reposo es una base de datos entera legible, asi que sigue dominando el puntaje por D7. El
transito decide el tramo alto: con todo cifrado en reposo, el 100 exige ademas una observacion de
que el canal va cifrado, y un canal en claro observado lo baja a 50.

Declarar una subcategoria mas tiene que costar mas evidencia; si no, la cobertura sube y el puntaje
se abarata a la vez, que es la combinacion que no se puede defender (docs/09 §77).
"""

from __future__ import annotations

from app.evaluation.rules._common import best_found, by_type, doc_claims, noting_unresolved
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-01"
CRITERION_VERSION = 2


@noting_unresolved({"storage_encrypted", "sse_algorithm", "bucket", "protocol", "ssl_policy"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    """Puntaje tecnico; la politica documental (`doc.claim(policy_exists)`) nunca lo eleva
    (docs/03 §3): solo se cita como contexto cuando hay cifrado deshabilitado."""

    resultado = _evaluate_technical(evidence)
    politica = best_found(doc_claims(evidence, "policy_exists"))
    if politica is None or resultado.final_score not in (0, 25):
        return resultado
    return resultado.model_copy(
        update={
            "explanation": (
                f"{resultado.explanation} Existe una politica documentada"
                " (doc.claim policy_exists) que no se refleja en la configuracion: es una brecha"
                " entre lo declarado y lo observado."
            ),
            "evidence_ids": [*resultado.evidence_ids, politica.id],
        }
    )


def _evaluate_technical(evidence: list[EvidenceInstance]) -> CriterionResult:
    relevant = by_type(evidence, "tf.encryption.config")
    # Un bucket o una base existen aunque no tengan configuracion de cifrado explicita: eso es
    # `unknown`, no "no aplicable" ni "no existe" (docs/02 §4).
    presentes = {
        e.subject_ref
        for e in by_type(evidence, "tf.resource.present")
        if e.subject_type in ("aws_s3_bucket", "aws_db_instance")
    }
    cubiertos = {e.subject_ref for e in relevant}
    sin_evidencia = sorted(presentes - cubiertos)

    if not relevant and not presentes:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.NO_APLICABLE,
            explanation="Sin recursos de almacenamiento o base de datos en el alcance.",
        )

    disabled = [e for e in relevant if e.value["estado"] == "disabled"]
    enabled = [e for e in relevant if e.value["estado"] == "enabled"]
    unknown = [e for e in relevant if e.value["estado"] == "unknown"]

    if sin_evidencia and not disabled:
        # Sin una observacion de fallo explicita, no se puede afirmar que todos cifren: 100 seria
        # una suposicion. Se puntua como insuficiente y se nombran los recursos sin evidencia.
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Sin evidencia de cifrado para: " + ", ".join(sin_evidencia) + ".",
            evidence_ids=[e.id for e in relevant],
        )

    if disabled:
        explanation = (
            "Cifrado deshabilitado en: " + ", ".join(e.subject_ref for e in disabled) + "."
            " La observacion tecnica prevalece sobre cualquier politica documental (D7)."
        )
        if unknown:
            explanation += f" {len(unknown)} recurso(s) con estado desconocido no se consideraron."
        # Ningun recurso resuelto cifra: ausencia explicita (0). Con alguno cifrado es parcial (25).
        score = 25 if enabled else 0
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=score,
            final_score=score,
            explanation=explanation,
            evidence_ids=[e.id for e in disabled + enabled],
        )

    if unknown:
        # Con un recurso aplicable en `unknown` no se puede afirmar que todo cifre: 100 seria una
        # suposicion (docs/03 §3).
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Cifrado desconocido en: "
            + ", ".join(e.subject_ref for e in unknown)
            + ". No se puede afirmar el 100.",
            evidence_ids=[e.id for e in enabled + unknown],
        )

    if enabled:
        return _con_transito(evidence, enabled)

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVIDENCIA_INSUFICIENTE,
        explanation="Todos los recursos tienen estado de cifrado desconocido (unknown).",
        evidence_ids=[e.id for e in unknown],
    )


def _con_transito(
    evidence: list[EvidenceInstance], en_reposo: list[EvidenceInstance]
) -> CriterionResult:
    """Todo cifrado en reposo: el tramo alto lo decide lo que se observe del canal (PR.DS-02)."""

    transito = by_type(evidence, "tf.transit_encryption.config")
    en_claro = [e for e in transito if e.value.get("estado") == "disabled"]
    cifrado = [e for e in transito if e.value.get("estado") == "enabled"]
    reposo = ", ".join(e.subject_ref for e in en_reposo)

    if en_claro:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=50,
            final_score=50,
            explanation=(
                f"Cifrado en reposo en todos los recursos ({reposo}), pero el dato viaja en claro:"
                f" {', '.join(e.subject_ref for e in en_claro)}."
            ),
            evidence_ids=[e.id for e in (*en_reposo, *en_claro)],
        )

    if cifrado:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=100,
            final_score=100,
            explanation=(
                f"Cifrado en reposo en todos los recursos ({reposo}) y en transito en"
                f" {', '.join(e.subject_ref for e in cifrado)}."
            ),
            evidence_ids=[e.id for e in (*en_reposo, *cifrado)],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=75,
        final_score=75,
        explanation=(
            f"Cifrado en reposo en todos los recursos ({reposo}), pero nada en el IaC dice como"
            " viaja el dato (PR.DS-02): sin un listener TLS ni `rds.force_ssl` no se puede afirmar"
            " el 100."
        ),
        evidence_ids=[e.id for e in en_reposo],
    )
