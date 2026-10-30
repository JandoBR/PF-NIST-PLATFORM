"""CRI-PR-04 — Configuracion y mantenimiento seguro del servidor (PR.PS-01, PR.PS-02; docs/03 §3).

Dos mitades de "el servidor esta en buen estado", y la segunda la añadio la Oleada C:

- **`PR.PS-01`** (practicas de gestion de la configuracion): tareas `lineinfile` sobre
  `sshd_config`. Un `PermitRootLogin yes` o `PasswordAuthentication yes` explicito domina sobre
  cualquier otro endurecimiento (igual que D7 en Terraform: la exposicion explicita prevalece).
- **`PR.PS-02`** ("el software se mantiene, reemplaza y retira"): una tarea de gestor de paquetes
  que **actualice versiones**. Es compuerta del 100, no una rama aparte: un `sshd_config`
  endurecido sobre un sistema sin parchear no es un servidor mantenido.

Un `state: present` no cuenta: deja la version que ya hubiera instalada. Y el tope por permisos
inseguros (25) se aplica **antes** de la compuerta: si el archivo es escribible por otros, el estado
de los paquetes no es lo que decide el puntaje.
"""

from __future__ import annotations

import re

from app.evaluation.rules._common import by_type
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-04"
CRITERION_VERSION = 2


def _directive_value(tasks: list[EvidenceInstance], directive: str) -> bool | None:
    """True=endurecido (no), False=explicito (yes), None=no se encontro la directiva.

    Solo se lee `line`, que es lo que queda escrito en el archivo. `regexp` dice que linea se
    reemplaza y puede contener ambos valores (`(yes|no)`): leerlo daba por endurecido un `yes`."""

    patron = re.compile(rf"^\s*{re.escape(directive)}\s+(\S+)", re.IGNORECASE)
    valor: bool | None = None
    for task in tasks:
        parametros = task.value["parametros"]
        if parametros.get("state") == "absent":
            continue
        coincide = patron.match(str(parametros.get("line", "")))
        if coincide is None:
            continue
        escrito = coincide.group(1).lower()
        if escrito == "no":
            valor = True
        elif escrito == "yes":
            valor = False
    return valor


def _permisos(
    evidence: list[EvidenceInstance],
) -> tuple[list[EvidenceInstance], list[EvidenceInstance]]:
    """`an.file.permissions` sobre `sshd_config`: (inseguros, no interpretables).

    Un modo simbolico relativo (`u+rwx`) no se puede traducir sin conocer los permisos actuales:
    no es seguro asumir que es inocuo, asi que el criterio no puede dar 100.
    """

    inseguros: list[EvidenceInstance] = []
    no_interpretables: list[EvidenceInstance] = []
    for e in by_type(evidence, "an.file.permissions"):
        if "sshd_config" not in e.value["ruta"]:
            continue
        try:
            modo = int(str(e.value["modo"]), 8)
        except ValueError:
            no_interpretables.append(e)
            continue
        if modo & 0o022:
            inseguros.append(e)
    return inseguros, no_interpretables


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    resultado = _evaluate_directives(evidence)
    inseguros, no_interpretables = _permisos(evidence)

    if (
        no_interpretables
        and resultado.estado == Estado.EVALUADO
        and (resultado.base_score or 0) > 25
    ):
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation=(
                "Permisos de sshd_config en un formato no interpretable ("
                + ", ".join(str(e.value["modo"]) for e in no_interpretables)
                + "): no se puede afirmar que sean seguros."
            ),
            evidence_ids=[e.id for e in no_interpretables],
        )

    if inseguros and resultado.estado == Estado.EVALUADO:
        score = min(resultado.base_score or 0, 25)
        return resultado.model_copy(
            update={
                "base_score": score,
                "final_score": score,
                "explanation": (
                    f"{resultado.explanation} sshd_config con permisos de escritura para grupo u"
                    " otros ("
                    + ", ".join(e.value["modo"] for e in inseguros)
                    + "): puntaje maximo 25."
                ),
                "evidence_ids": [*resultado.evidence_ids, *(e.id for e in inseguros)],
            }
        )

    return _con_mantenimiento(evidence, resultado)


def _con_mantenimiento(
    evidence: list[EvidenceInstance], resultado: CriterionResult
) -> CriterionResult:
    """El 100 exige ademas una tarea que mantenga el software al dia (PR.PS-02).

    Solo toca el tramo alto: si el SSH ya no esta endurecido, ese es el problema y el estado de los
    paquetes no lo empeora ni lo arregla.
    """

    if resultado.estado != Estado.EVALUADO or resultado.base_score != 100:
        return resultado

    paquetes = by_type(evidence, "an.package.state")
    actualizan = [e for e in paquetes if e.value.get("intencion") == "actualiza"]
    if actualizan:
        return resultado.model_copy(
            update={
                "explanation": (
                    f"{resultado.explanation} El software se mantiene al dia ("
                    + ", ".join(sorted({e.value["modulo"] for e in actualizan}))
                    + ")."
                ),
                "evidence_ids": [*resultado.evidence_ids, *(e.id for e in actualizan)],
            }
        )

    detalle = (
        "las tareas de paquetes solo instalan o eliminan, no actualizan versiones"
        if paquetes
        else "ninguna tarea actualiza paquetes"
    )
    return resultado.model_copy(
        update={
            "base_score": 75,
            "final_score": 75,
            "explanation": (
                f"{resultado.explanation} Pero {detalle}: un sshd_config endurecido sobre un"
                " sistema sin parchear no es un servidor mantenido (PR.PS-02)."
            ),
            "evidence_ids": [*resultado.evidence_ids, *(e.id for e in paquetes)],
        }
    )


def _evaluate_directives(evidence: list[EvidenceInstance]) -> CriterionResult:
    lineinfile_tasks = [
        e for e in by_type(evidence, "an.task.config") if e.value["modulo"] == "lineinfile"
    ]
    sshd_tasks = [
        e for e in lineinfile_tasks if "sshd_config" in e.value["parametros"].get("path", "")
    ]

    if not sshd_tasks:
        return CriterionResult(
            criterion_id=CRITERION_ID,
            criterion_version=CRITERION_VERSION,
            estado=Estado.EVIDENCIA_INSUFICIENTE,
            explanation="Sin tareas de Ansible sobre sshd_config evaluables.",
        )

    permit_root_login = _directive_value(sshd_tasks, "PermitRootLogin")
    password_auth = _directive_value(sshd_tasks, "PasswordAuthentication")
    valores = [permit_root_login, password_auth]

    if valores.count(False) == 2:
        score = 0
        explanation = (
            "PermitRootLogin yes y PasswordAuthentication yes explicitos en sshd_config: sin"
            " ningun endurecimiento."
        )
    elif False in valores:
        score = 25
        explanation = (
            "Directiva insegura explicita en sshd_config "
            "(PermitRootLogin/PasswordAuthentication yes)."
        )
    elif valores.count(True) == 2:
        score = 100
        explanation = "PermitRootLogin no y PasswordAuthentication no declarados en sshd_config."
    elif valores.count(True) == 1:
        score = 75
        explanation = "Solo una de las dos directivas de endurecimiento esta declarada."
    else:
        score = 50
        explanation = (
            "sshd_config gestionado por Ansible sin opciones explicitas de endurecimiento."
        )

    return CriterionResult(
        criterion_id=CRITERION_ID,
        criterion_version=CRITERION_VERSION,
        estado=Estado.EVALUADO,
        base_score=score,
        final_score=score,
        explanation=explanation,
        evidence_ids=[e.id for e in sshd_tasks],
    )
