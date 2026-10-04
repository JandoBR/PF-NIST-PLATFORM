"""CRI-PR-03 — Acceso administrativo restringido (docs/03 §3).

MVP: solo evalua `tf.security_group.rules`. La evidencia de `an.task.config` (sshd) listada en el
catalogo se incorporara cuando exista el adaptador de Ansible; hasta entonces el criterio se basa
solo en la exposicion de puertos administrativos en los security groups.
"""

from __future__ import annotations

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
    desde, hasta = rule["puerto_desde"], rule["puerto_hasta"]
    if desde is None or hasta is None:
        return True  # rango sin acotar (p. ej. protocolo -1): se asume que cubre el puerto.
    if not isinstance(desde, int) or not isinstance(hasta, int):
        # Puerto como expresion sin resolver (`var.ssh_port`): no se adivina. Queda declarado como
        # limitacion (`tf.expression.unresolved`), igual que un CIDR sin resolver.
        return False
    return any(desde <= puerto <= hasta for puerto in PUERTOS_ADMINISTRATIVOS)


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
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVALUADO,
            base_score=25,
            final_score=25,
            explanation="Puertos administrativos (22/3389) expuestos a Internet en: "
            + ", ".join(sg.subject_ref for sg in expuestos)
            + ". Es configuracion declarada; no demuestra accesibilidad efectiva.",
            evidence_ids=[sg.id for sg in expuestos],
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
