"""CRI-PR-03 — Acceso administrativo restringido (docs/03 §3).

MVP: solo evalua `tf.security_group.rules`. La evidencia de `an.task.config` (sshd) listada en el
catalogo se incorporara cuando exista el adaptador de Ansible; hasta entonces el criterio se basa
solo en la exposicion de puertos administrativos en los security groups.
"""

from __future__ import annotations

from app.adapters.terraform.adapter import CIDR_DESCONOCIDO
from app.evaluation.rules._common import by_type, noting_unresolved
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-03"
CRITERION_VERSION = 1
PUERTOS_ADMINISTRATIVOS = {22, 3389}
CIDRS_ABIERTOS = {"0.0.0.0/0", "::/0"}


def _expone_administracion(rule: dict) -> bool:
    if rule["direccion"] != "ingress" or rule["cidr"] not in CIDRS_ABIERTOS:
        return False
    if _puerto_sin_resolver(rule):
        return False  # no se adivina: ver `_indeterminada`
    return _cubre_administracion(rule)


def _puerto_sin_resolver(rule: dict) -> bool:
    """El puerto es una expresion que el parser no resolvio (`var.ssh_port`)."""

    return any(
        puerto is not None and not isinstance(puerto, int)
        for puerto in (rule["puerto_desde"], rule["puerto_hasta"])
    )


def _cubre_administracion(rule: dict) -> bool:
    desde, hasta = rule["puerto_desde"], rule["puerto_hasta"]
    if desde is None or hasta is None:
        return True  # rango sin acotar (p. ej. protocolo -1): se asume que cubre el puerto.
    return any(desde <= puerto <= hasta for puerto in PUERTOS_ADMINISTRATIVOS)


def _indeterminada(rule: dict) -> bool:
    """Ingress que podria exponer administracion a Internet y no se puede saber: abierto en un
    puerto sin resolver, o en un puerto administrativo (o sin resolver) desde un CIDR sin resolver.
    """

    if rule["direccion"] != "ingress":
        return False
    sin_puerto = _puerto_sin_resolver(rule)
    if rule["cidr"] in CIDRS_ABIERTOS:
        return sin_puerto
    if rule["cidr"] == CIDR_DESCONOCIDO:
        return sin_puerto or _cubre_administracion(rule)
    return False


@noting_unresolved({"cidr_blocks", "ipv6_cidr_blocks", "from_port", "to_port"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    relevant = by_type(evidence, "tf.security_group.rules")
    if not relevant:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Sin security groups evaluables en el alcance.",
        )

    expuestos = [sg for sg in relevant if any(_expone_administracion(r) for r in sg.value)]

    if expuestos:
        # Administracion abierta a Internet es una exposicion explicita, no una implementacion
        # parcial: 0, como una base de datos publica en PR-05.
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=0,
            final_score=0,
            explanation="Puertos administrativos (22/3389) expuestos a Internet en: "
            + ", ".join(sg.subject_ref for sg in expuestos)
            + ". Es configuracion declarada; no demuestra accesibilidad efectiva.",
            evidence_ids=[sg.id for sg in expuestos],
        )

    indeterminados = [sg for sg in relevant if any(_indeterminada(r) for r in sg.value)]
    if indeterminados:
        # Puerto u origen desconocido: ni 0 (no se sabe que exponga administracion) ni 100 (no
        # se puede afirmar que no lo haga).
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Reglas de entrada con el puerto o el origen sin resolver en: "
            + ", ".join(sg.subject_ref for sg in indeterminados)
            + ". No se puede concluir si exponen administracion.",
            evidence_ids=[sg.id for sg in indeterminados],
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=100,
        final_score=100,
        explanation="Ningun security group expone puertos administrativos a 0.0.0.0/0 o ::/0.",
        evidence_ids=[sg.id for sg in relevant],
    )
