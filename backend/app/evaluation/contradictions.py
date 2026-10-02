"""Deteccion de contradicciones entre fuentes (docs/02 §5, docs/11 OP-04).

Deterministas y sin IA: comparan dos lados *ya extraidos como evidencia* sobre la misma propiedad.

- **Tecnico vs documental** -- prevalece la observacion tecnica (D7).
- **Documental vs documental** -- dos documentos distintos declaran valores diferentes.

Solo se comparan evidencias del mismo `scope` (docs/02 §5: entornos distintos no se contradicen).
Un hallazgo por criterio y por clase de contradiccion, nunca uno por recurso.

**Efecto en el puntaje:** una afirmacion documental que contradice a otra fuente **no cuenta** para
puntuar (`exclude_contradicted`): el criterio se evalua como si esa afirmacion no existiera, y el
hallazgo y una nota en la explicacion dejan constancia. La evidencia tecnica nunca se excluye.
Vive en `evaluation` (no en `recommendations`) porque el motor la necesita antes de puntuar; los
hallazgos (`recommendations/contradictions.py`) solo la presentan.
"""


from __future__ import annotations

from collections.abc import Callable, Iterable

from pydantic import BaseModel

from app.evaluation.rules._common import best_found, by_type, doc_claims
from app.evaluation.rules.pr02_backup import retencion_politica_dias
from app.schemas.evidence import EvidenceInstance

_PR02 = "CRI-PR-02"
_GV01 = "CRI-GV-01"
_PR05 = "CRI-PR-05"


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
    politicas = [c for c in doc_claims(evidence, "backup_policy") if c.value.get("encontrado")]
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
                f"{detalle}. Prevalece lo tecnico (D7).",
                ids,
                _unique(p.id for p, _, _ in menores),
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
    criterion_id: str,
    titulo: str,
    campo: str,
) -> list[Contradiction]:
    """Dos documentos distintos del mismo `scope` con valores diferentes para la misma propiedad."""

    claims = [c for c in doc_claims(evidence, tipo) if c.value.get("encontrado")]
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
        findings.append(
            _finding(
                criterion_id,
                titulo,
                "media",
                f"{detalle}. Se registran ambos; ninguno cuenta para el puntaje.",
                [c.id for c in lados],
                [c.id for cs in valores.values() for c in cs],
            )
        )
    return findings


def _frecuencia(claim: EvidenceInstance) -> str | None:
    valor = (claim.value.get("contenido") or {}).get("frecuencia")
    return str(valor).lower() if valor else None


def _unique(ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def detect(evidence: list[EvidenceInstance]) -> list[Contradiction]:
    return [
        *_backup_vs_policy(evidence),
        *_database_exposure_vs_policy(evidence),
        *_documents_disagree(
            evidence,
            "backup_policy",
            retencion_politica_dias,
            _PR02,
            "Dos documentos declaran retenciones de backup distintas",
            "retencion (dias)",
        ),
        *_documents_disagree(
            evidence,
            "policy_review",
            _frecuencia,
            _GV01,
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
