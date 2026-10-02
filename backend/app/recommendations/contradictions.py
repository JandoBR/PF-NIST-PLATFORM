"""Hallazgos de contradiccion (docs/02 §5, docs/11 OP-04).

Deterministas y sin IA: comparan dos lados *ya extraidos como evidencia* sobre la misma propiedad.

- **Tecnico vs documental** -- prevalece la observacion tecnica (D7). Los criterios ya puntuan con
  el valor tecnico; aqui solo se deja constancia de la incoherencia, citando ambos lados.
- **Documental vs documental** -- dos documentos distintos declaran valores diferentes.

Solo se comparan evidencias del mismo `scope` (docs/02 §5: entornos distintos no se contradicen).
Un hallazgo por criterio y por clase de contradiccion, nunca uno por recurso: no penalizan doble ni
alteran ningun puntaje.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.evaluation.rules._common import best_found, by_type, doc_claims
from app.evaluation.rules.pr02_backup import retencion_politica_dias
from app.recommendations.findings import Finding
from app.schemas.evidence import EvidenceInstance

_PR02 = "CRI-PR-02"
_GV01 = "CRI-GV-01"


def _finding(
    criterion_id: str,
    titulo: str,
    severidad: str,
    detalle: str,
    evidence_ids: list[str],
) -> Finding:
    return Finding(
        criterion_id=criterion_id,
        titulo=titulo,
        tipo="contradiccion",
        severidad=severidad,
        score=None,
        detalle=detalle,
        evidence_ids=evidence_ids,
    )


def _backup_vs_policy(evidence: list[EvidenceInstance]) -> list[Finding]:
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

    findings: list[Finding] = []
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
            )
        )
    return findings


def _documents_disagree(
    evidence: list[EvidenceInstance],
    tipo: str,
    valor: Callable[[EvidenceInstance], object],
    criterion_id: str,
    titulo: str,
    campo: str,
) -> list[Finding]:
    """Dos documentos distintos del mismo `scope` con valores diferentes para la misma propiedad."""

    claims = [c for c in doc_claims(evidence, tipo) if c.value.get("encontrado")]
    por_valor: dict[tuple[str, object], list[EvidenceInstance]] = {}
    for claim in claims:
        v = valor(claim)
        if v is not None:
            por_valor.setdefault((claim.scope, v), []).append(claim)

    scopes = {scope for scope, _ in por_valor}
    findings: list[Finding] = []
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
                f"{detalle}. Se registran ambos; el criterio no cambia su puntaje.",
                [c.id for c in lados],
            )
        )
    return findings


def _frecuencia(claim: EvidenceInstance) -> str | None:
    valor = (claim.value.get("contenido") or {}).get("frecuencia")
    return str(valor).lower() if valor else None


def _unique(ids: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def detect_contradictions(evidence: list[EvidenceInstance]) -> list[Finding]:
    return [
        *_backup_vs_policy(evidence),
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
