"""Deteccion de contradicciones entre fuentes (docs/02 §5, docs/11 OP-04).

Deterministas y sin IA: comparan dos lados *ya extraidos como evidencia* sobre la misma propiedad.

- **Tecnico vs documental** -- prevalece la observacion tecnica (D7).
- **Documental vs documental** -- dos documentos distintos declaran valores diferentes (solo
  afirmaciones vigentes: un plan no contradice la politica en vigor, y la negacion contra una
  vigente la trata `_absence_disagreement`, docs/09 §114).

Solo se comparan evidencias del mismo `scope` (docs/02 §5: entornos distintos no se contradicen).
Un hallazgo por criterio y por clase de contradiccion, nunca uno por recurso.

**Efecto en el puntaje:** una afirmacion documental que afirma un hecho que otra fuente desmiente
(la politica dice "hay respaldos" y Terraform los deshabilita; "la base no es publica" y lo es; dos
documentos con valores distintos) **no cuenta** para
puntuar el criterio de la contradiccion (`excluded_by_criterion`): ese criterio se evalua como si la
afirmacion no existiera, y el hallazgo y una nota en la explicacion dejan constancia. Los demas
criterios que leen la misma afirmacion por otra propiedad (p. ej. `RC-02`, que mira la verificacion
de integridad de una `backup_policy` cuya retencion contradice a Terraform) la siguen usando. La
evidencia tecnica nunca se excluye. Una politica que fija un **requisito** que la configuracion no
alcanza (retencion configurada menor que la documentada) no se excluye: es un incumplimiento, la
regla del criterio lo puntua y el hallazgo lo muestra.
Vive en `evaluation` (no en `recommendations`) porque el motor la necesita antes de puntuar; los
hallazgos (`recommendations/contradictions.py`) solo la presentan.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel

from app.evaluation.rules._common import (
    POLITICA_GENERICA,
    best_found,
    by_type,
    doc_claims,
    es_ausencia_declarada,
    es_vigente,
    estado_declarado,
    faceta,
    facetas_compatibles,
    mejor_declarada,
    proceso_faceta,
)
from app.evaluation.rules.pr02_backup import retencion_politica_dias
from app.evaluation.schemas import CriterionResult
from app.schemas.evidence import EvidenceInstance

_PR02 = "CRI-PR-02"
_GV01 = "CRI-GV-01"
_GV04 = "CRI-GV-04"
_PR05 = "CRI-PR-05"

#: Criterios que leen cada tipo de afirmacion. `detect` es global y un hallazgo pertenece a un
#: criterio: sin este mapa una contradiccion documento-vs-documento sobre "existe/no existe" no
#: sabria a que puntaje afecta (docs/09 §106).
_CRITERIOS_POR_TIPO: dict[str, tuple[str, ...]] = {
    "policy_exists": ("CRI-GV-01",),
    "policy_review": ("CRI-GV-01", "CRI-GV-04"),
    "role_assigned": ("CRI-GV-02",),
    "risk_tolerance": ("CRI-GV-03",),
    "backup_policy": ("CRI-PR-02", "CRI-RC-01", "CRI-RC-02"),
    "notification_list": ("CRI-DE-03", "CRI-RC-03", "CRI-RS-03"),
    "escalation_path": ("CRI-RS-01",),
    "org_context": ("CRI-GV-05",),
    "supplier_program": ("CRI-GV-06",),
    "training_program": ("CRI-PR-07",),
    "exposure_policy": ("CRI-PR-05",),
    "data_inventory": ("CRI-ID-01", "CRI-ID-02", "CRI-ID-04"),
}

#: `process_defined` sirve a varios criterios segun el proceso que declara el documento; la faceta
#: sale de `_common.faceta`, asi que dos procesos distintos nunca comparten contradiccion.
_CRITERIOS_POR_FACETA: dict[str, str] = {
    "respuesta": "CRI-RS-01",
    "recuperacion": "CRI-RC-01",
    "riesgos": "CRI-ID-03",
    "analisis incidentes": "CRI-RS-02",
    "contencion": "CRI-RS-04",
    "mejora": "CRI-ID-05",
    "revision": "CRI-GV-04",
}


def _criterios_de(claim: EvidenceInstance) -> tuple[str, ...]:
    """Criterios a los que afecta una afirmacion de ese tipo (y proceso, si aplica)."""

    tipo = str(claim.value.get("tipo_afirmacion"))
    if tipo == "process_defined":
        criterio = _CRITERIOS_POR_FACETA.get(proceso_faceta(claim) or "")
        return (criterio,) if criterio is not None else ()
    return _CRITERIOS_POR_TIPO.get(tipo, ())


class Contradiction(BaseModel):
    criterion_id: str
    titulo: str
    severidad: str
    detalle: str
    #: Ambos lados, citados.
    evidence_ids: list[str]
    #: `doc.claim` que dejan de contar para puntuar (nunca evidencia tecnica).
    excluded_claim_ids: list[str]


def _finding(
    criterion_id: str,
    titulo: str,
    severidad: str,
    detalle: str,
    evidence_ids: list[str],
    excluded_claim_ids: list[str],
) -> Contradiction:
    return Contradiction(
        criterion_id=criterion_id,
        titulo=titulo,
        severidad=severidad,
        detalle=detalle,
        evidence_ids=evidence_ids,
        excluded_claim_ids=excluded_claim_ids,
    )


def _backup_vs_policy(evidence: list[EvidenceInstance]) -> list[Contradiction]:
    politicas = [c for c in doc_claims(evidence, "backup_policy") if es_vigente(c)]
    configs = [
        e
        for e in by_type(evidence, "tf.backup.config")
        if e.value.get("retencion_dias") is not None
    ]
    deshabilitados: list[tuple[EvidenceInstance, EvidenceInstance]] = []
    menores: list[tuple[EvidenceInstance, EvidenceInstance, int]] = []

    for politica in politicas:
        dias = retencion_politica_dias(politica)
        declara_respaldo = (politica.value.get("contenido") or {}).get("respaldo") is True
        for config in configs:
            if config.scope != politica.scope:
                continue
            if declara_respaldo and config.value["retencion_dias"] == 0:
                deshabilitados.append((politica, config))
            elif dias is not None and config.value["retencion_dias"] < dias:
                menores.append((politica, config, dias))

    findings: list[Contradiction] = []
    if deshabilitados:
        ids = _unique(e.id for par in deshabilitados for e in par)
        recursos = ", ".join(sorted({c.subject_ref for _, c in deshabilitados}))
        findings.append(
            _finding(
                _PR02,
                "La politica documenta respaldos pero Terraform los deshabilita",
                "alta",
                f"La politica documental declara respaldos; la configuracion de {recursos} tiene"
                " retencion 0 (backups deshabilitados). Prevalece lo tecnico (D7).",
                ids,
                _unique(p.id for p, _ in deshabilitados),
            )
        )
    if menores:
        ids = _unique(e.id for p, c, _ in menores for e in (p, c))
        detalle = "; ".join(
            f"{c.subject_ref}: politica {d} dias vs configurado {c.value['retencion_dias']}"
            for _, c, d in sorted(menores, key=lambda t: t[1].subject_ref)
        )
        findings.append(
            _finding(
                _PR02,
                "La retencion configurada es menor que la de la politica",
                "media",
                f"{detalle}. La configuracion incumple la politica.",
                ids,
                # La politica no afirma un hecho falso: fija un requisito que la configuracion no
                # cumple. Sigue contando, y PR-02 lo puntua como retencion < politica (50). Si se
                # excluyera, incumplir la politica valdria lo mismo que no tenerla (75).
                [],
            )
        )
    return findings


def _database_exposure_vs_policy(evidence: list[EvidenceInstance]) -> list[Contradiction]:
    """La politica prohibe bases de datos publicas y Terraform declara `publicly_accessible = true`
    (el ejemplo canonico de docs/02 §5). Prevalece Terraform: PR-05 ya puntua 0."""

    politicas = [
        c
        for c in doc_claims(evidence, "exposure_policy")
        if c.value.get("encontrado")
        and (c.value.get("contenido") or {}).get("bases_publicas_permitidas") is False
    ]
    publicas = [e for e in by_type(evidence, "tf.db_exposure.config") if e.value["publico"] is True]
    pares = [(p, d) for p in politicas for d in publicas if p.scope == d.scope]
    if not pares:
        return []
    recursos = ", ".join(sorted({d.subject_ref for _, d in pares}))
    return [
        _finding(
            _PR05,
            "La politica prohibe bases de datos publicas pero Terraform las expone",
            "alta",
            f"La politica documental no permite bases de datos accesibles desde Internet;"
            f" {recursos} declara publicly_accessible = true. Prevalece lo tecnico (D7).",
            _unique(e.id for par in pares for e in par),
            _unique(p.id for p, _ in pares),
        )
    ]


def _documents_disagree(
    evidence: list[EvidenceInstance],
    tipo: str,
    valor: Callable[[EvidenceInstance], object],
    criterion_ids: tuple[str, ...],
    titulo: str,
    campo: str,
) -> list[Contradiction]:
    """Dos documentos distintos del mismo `scope` con valores diferentes para la misma propiedad.

    Solo compiten las afirmaciones **vigentes**: un plan con otro valor no contradice a la politica
    en vigor, y la negacion contra una afirmacion vigente ya la trata `_absence_disagreement`
    (docs/09 §106, §114)."""

    claims = [c for c in doc_claims(evidence, tipo) if es_vigente(c)]
    por_valor: dict[tuple[str, object], list[EvidenceInstance]] = {}
    for claim in claims:
        v = valor(claim)
        if v is not None:
            por_valor.setdefault((claim.scope, v), []).append(claim)

    scopes = {scope for scope, _ in por_valor}
    findings: list[Contradiction] = []
    for scope in sorted(scopes):
        valores = {v: cs for (s, v), cs in por_valor.items() if s == scope}
        documentos = {c.subject_ref for cs in valores.values() for c in cs}
        if len(valores) < 2 or len(documentos) < 2:
            continue
        # un representante por valor (el de mayor confianza): ambos lados citados
        lados = [best_found(cs) for _, cs in sorted(valores.items(), key=lambda kv: str(kv[0]))]
        lados = [c for c in lados if c is not None]
        detalle = "; ".join(f"{c.subject_ref} declara {campo}={valor(c)}" for c in lados)
        findings.extend(
            _finding(
                criterion_id,
                titulo,
                "media",
                f"{detalle}. Se registran ambos; ninguno cuenta para el puntaje.",
                [c.id for c in lados],
                [c.id for cs in valores.values() for c in cs],
            )
            for criterion_id in criterion_ids
        )
    return findings


def _absence_disagreement(evidence: list[EvidenceInstance]) -> list[Contradiction]:
    """Un documento niega la practica y otro la declara vigente (docs/02 §5, docs/09 §106).

    Se compara por **faceta**, no solo por tipo: una negacion del proceso de recuperacion no
    contradice el proceso de respuesta de otro documento, y antes excluia sus afirmaciones del
    criterio equivocado (docs/09 §108). Una `policy_exists` se compara por la politica que nombra:
    negar la politica de proveedores no contradice la politica de seguridad de la informacion, que
    es la que evalua GV-01 (docs/09 §109); una negacion sin nombre sigue hablando de cualquier
    politica. Es el caso de borde de `aplicar_estado_declarado`: la ausencia no se impone sobre
    otro documento. Se registran ambos lados y, como en cualquier documento-vs-documento, ninguno
    cuenta para puntuar el criterio afectado; sin exclusion, la regla acreditaria la version
    vigente y la negacion quedaria invisible."""

    claims = [
        c
        for c in by_type(evidence, "doc.claim")
        if c.value.get("encontrado") and c.limitations is None
    ]
    grupos: dict[tuple[str, str], list[EvidenceInstance]] = {}
    for claim in claims:
        clave = (claim.scope, str(claim.value.get("tipo_afirmacion")))
        grupos.setdefault(clave, []).append(claim)

    findings: list[Contradiction] = []
    for clave, grupo in sorted(grupos.items()):
        tipo = clave[1]
        pares = [
            (ausencia, vigente)
            for ausencia in grupo
            if es_ausencia_declarada(ausencia)
            for vigente in grupo
            if estado_declarado(vigente) == "vigente"
            and ausencia.subject_ref != vigente.subject_ref
            and facetas_compatibles(faceta(ausencia), faceta(vigente))
        ]
        if not pares:
            continue
        ausencias = _unique_claims(ausencia for ausencia, _ in pares)
        vigentes = _unique_claims(vigente for _, vigente in pares)
        candidatos = (mejor_declarada(ausencias), best_found(vigentes))
        lados = [lado for lado in candidatos if lado is not None]
        criterios = sorted(
            {criterio for claim in ausencias + vigentes for criterio in _criterios_de(claim)}
        )
        if not criterios:
            continue
        facetas = sorted(
            {nombre for claim in ausencias + vigentes if (nombre := _faceta_nombre(claim))}
        )
        practica = tipo if len(facetas) != 1 else f"{tipo} ({facetas[0]})"
        detalle = (
            f"{' y '.join(sorted({c.subject_ref for c in ausencias}))} declara que {practica} no"
            f" existe; {' y '.join(sorted({c.subject_ref for c in vigentes}))} lo declara vigente."
            " Se registran ambos; ninguno cuenta para el puntaje."
        )
        for criterio in criterios:
            findings.append(
                _finding(
                    criterio,
                    "Dos documentos contradicen la existencia de la practica",
                    "media",
                    detalle,
                    [c.id for c in lados],
                    [c.id for c in ausencias + vigentes],
                )
            )
    return findings


def _frecuencia(claim: EvidenceInstance) -> str | None:
    valor = (claim.value.get("contenido") or {}).get("frecuencia")
    return str(valor).lower() if valor else None


def _unique(ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _faceta_nombre(claim: EvidenceInstance) -> str:
    clave = faceta(claim)
    nombre = clave[1] if len(clave) > 1 else ""
    return "" if nombre == POLITICA_GENERICA else nombre


def _unique_claims(claims: Iterable[EvidenceInstance]) -> list[EvidenceInstance]:
    return sorted({claim.id: claim for claim in claims}.values(), key=lambda c: c.id)


def detect(evidence: list[EvidenceInstance]) -> list[Contradiction]:
    return [
        *_backup_vs_policy(evidence),
        *_database_exposure_vs_policy(evidence),
        *_absence_disagreement(evidence),
        *_documents_disagree(
            evidence,
            "backup_policy",
            retencion_politica_dias,
            (_PR02,),
            "Dos documentos declaran retenciones de backup distintas",
            "retencion (dias)",
        ),
        *_documents_disagree(
            evidence,
            "policy_review",
            _frecuencia,
            (_GV01,),
            "Dos documentos declaran frecuencias de revision distintas",
            "frecuencia",
        ),
    ]


def exclude_contradicted(
    evidence: list[EvidenceInstance],
) -> tuple[list[EvidenceInstance], list[Contradiction]]:
    """Evidencia que el motor puede usar para puntuar (sin las afirmaciones contradichas) y las
    contradicciones encontradas. Sin contradicciones devuelve la misma lista."""

    contradicciones = detect(evidence)
    excluidas = {i for c in contradicciones for i in c.excluded_claim_ids}
    if not excluidas:
        return evidence, contradicciones
    return [e for e in evidence if e.id not in excluidas], contradicciones


def excluded_by_criterion(contradicciones: list[Contradiction]) -> dict[str, set[str]]:
    """Por criterio, los `doc.claim` que no cuentan para puntuarlo. La contradiccion es sobre una
    propiedad de un criterio (retencion, frecuencia de revision, exposicion): no invalida la
    afirmacion para los demas criterios que la leen."""

    excluidas: dict[str, set[str]] = {}
    for c in contradicciones:
        if c.excluded_claim_ids:
            excluidas.setdefault(c.criterion_id, set()).update(c.excluded_claim_ids)
    return excluidas


def cap_contradicted(
    results: list[CriterionResult],
    current: list[Contradiction],
    previous_scores: dict[str, float | None],
) -> list[CriterionResult]:
    """Mientras un criterio tenga una contradiccion, su puntaje no puede subir respecto a la
    evaluacion anterior: `final_score` queda como maximo en el anterior (puede bajar, nunca subir).

    No penaliza, solo no premia: la mejora tecnica no cuenta hasta que la politica y la
    infraestructura dejen de contradecirse. Sin puntaje anterior (criterio no evaluado) no hay con
    que comparar. `base_score` no se toca: es lo que dicen las reglas; `final_score` es lo que
    cuenta.
    """

    contradichos = {c.criterion_id for c in current}

    capped = []
    for r in results:
        anterior = previous_scores.get(r.criterion_id)
        if (
            r.criterion_id not in contradichos
            or anterior is None
            or r.final_score is None
            or r.final_score <= anterior
        ):
            capped.append(r)
            continue
        capped.append(
            r.model_copy(
                update={
                    "final_score": anterior,
                    "explanation": (
                        f"{r.explanation} Contradiccion sin resolver: el puntaje no puede superar"
                        f" el de la evaluacion anterior ({anterior:g}) hasta que la politica y la"
                        " infraestructura dejen de contradecirse."
                    ),
                }
            )
        )
    return capped
