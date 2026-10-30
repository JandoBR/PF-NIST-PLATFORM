"""CRI-PR-08 - Gestion de identidades y autenticacion (PR.AA-01, PR.AA-03, docs/03).

Dos subcategorias, dos señales distintas y deterministas:

- **`PR.AA-01`** ("se gestionan las identidades y credenciales"): que las identidades esten
  declaradas en el IaC. Un rol creado a mano en la consola no esta gestionado; uno declarado en
  Terraform tiene dueño, revision e historial.
- **`PR.AA-03`** ("los usuarios, servicios y hardware se autentican"): como de fuerte es esa
  autenticacion -- la politica de contrasenas de la cuenta y si alguna politica exige MFA.

El umbral de longitud es **14**, el del CIS AWS Foundations Benchmark, no una cifra inventada.

**La asimetria deliberada de la rubrica:** una politica de contrasenas *declarada y debil* puntua
mas bajo (0 o 25) que *no declarar ninguna* (50). Parece al reves y no lo es: en IaC la ausencia no
prueba la ausencia -- la cuenta puede tener su politica puesta fuera de Terraform --, mientras que
una longitud minima de 6 escrita en el `.tf` es una observacion de un control debil. Es el mismo
principio del silencio documental (docs/09 §60) aplicado a una señal tecnica: para penalizar hace
falta ver algo, no dejar de verlo.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, noting_unresolved, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-08"

#: Longitud minima de contraseña que el CIS AWS Foundations Benchmark pide para la cuenta.
LONGITUD_CIS = 14
#: Por debajo de esto no hay control que valorar, es una contraseña debil declarada.
LONGITUD_MINIMA_ACEPTABLE = 8


def _identidades(evidence: list[EvidenceInstance]) -> list[EvidenceInstance]:
    """Recursos IAM que *son* una identidad o un permiso gestionado, no la config de la cuenta."""

    return [
        e
        for e in by_type(evidence, "tf.resource.present")
        if str(e.value.get("tipo", "")).startswith("aws_iam_")
        and e.value.get("tipo") != "aws_iam_account_password_policy"
    ]


@noting_unresolved(
    {
        "minimum_password_length",
        "require_symbols",
        "require_numbers",
        "max_password_age",
        "password_reuse_prevention",
    }
)
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    identidades = _identidades(evidence)
    config = by_type(evidence, "tf.identity.config")
    politicas = [e for e in config if e.value.get("tipo") == "politica_de_contrasenas"]
    mfa = [e for e in config if e.value.get("tipo") == "mfa"]

    if not identidades and not politicas:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "El IaC no declara recursos IAM ni politica de contrasenas. No se puede concluir que"
            " no haya identidades gestionadas: pueden existir fuera de Terraform.",
        )

    citadas = [e.id for e in (*identidades, *config)]
    nombres = ", ".join(sorted({str(e.value.get("tipo")) for e in identidades})) or "ninguno"
    inventario = f"{len(identidades)} recurso(s) IAM declarado(s) ({nombres})."

    # `mfa_requerido` es None cuando el documento de la politica no es literal: eso no es un "no".
    exige_mfa = any(e.value.get("mfa_requerido") is True for e in mfa)

    declaradas = [e for e in politicas if e.value.get("longitud_minima") is not None]
    if not declaradas:
        detalle = (
            "hay una politica de contrasenas pero su longitud minima no es literal"
            if politicas
            else "no hay politica de contrasenas en el IaC"
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            f"Identidades gestionadas en IaC, pero {detalle}, asi que la fuerza de la autenticacion"
            f" (PR.AA-03) no se puede observar. {inventario}",
            citadas,
        )

    longitud = min(int(e.value["longitud_minima"]) for e in declaradas)

    if longitud < LONGITUD_MINIMA_ACEPTABLE:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            f"La politica de contrasenas declara una longitud minima de {longitud} caracteres:"
            f" por debajo de cualquier umbral defendible. {inventario}",
            citadas,
        )

    if longitud < LONGITUD_CIS:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            25,
            f"La politica de contrasenas exige {longitud} caracteres, por debajo de los"
            f" {LONGITUD_CIS} del CIS AWS Foundations Benchmark. {inventario}",
            citadas,
        )

    if not exige_mfa:
        pendiente = (
            "ninguna politica exige `aws:MultiFactorAuthPresent`"
            if mfa
            else "no hay ninguna politica que exija MFA"
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            f"La politica de contrasenas cumple el umbral ({longitud} caracteres), pero"
            f" {pendiente}: la contrasena sigue siendo el unico factor. {inventario}",
            citadas,
        )

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        100,
        f"Identidades declaradas en IaC, politica de contrasenas de {longitud} caracteres y una"
        f" politica que exige MFA. {inventario}",
        citadas,
    )
