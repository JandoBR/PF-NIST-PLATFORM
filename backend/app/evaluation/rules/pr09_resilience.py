"""CRI-PR-09 - Resiliencia y capacidad de la plataforma (PR.IR-03, PR.IR-04, docs/03).

Dos cosas que suenan parecidas y no lo son, y por eso son dos subcategorias:

- **`PR.IR-03`** ("mecanismos para alcanzar los requisitos de resiliencia"): que el servicio
  sobreviva a la caida de una zona. En el IaC eso es `multi_az` o una replica de lectura.
- **`PR.IR-04`** ("capacidad de recursos adecuada para asegurar la disponibilidad"): que el servicio
  aguante la carga. En el IaC eso es un grupo de autoescalado **que pueda crecer**.

Un `min_size` igual al `max_size` no cuenta: es capacidad fija con otro nombre. Y un `multi_az`
ausente no cuenta como `false`, aunque el defecto de AWS lo sea: el silencio del `.tf` y una
negacion escrita se tratan distinto, igual que en `CRI-PR-08` (docs/09 §91).
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, noting_unresolved, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-PR-09"

#: Mecanismos que sostienen `PR.IR-03`: el servicio sobrevive a la perdida de una zona.
_ALTA_DISPONIBILIDAD = frozenset({"multi_az", "replica"})


@noting_unresolved({"multi_az", "replicate_source_db", "min_size", "max_size", "desired_capacity"})
def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    señales = by_type(evidence, "tf.resilience.config")
    if not señales:
        return result(
            CRITERION_ID,
            Estado.NO_APLICABLE,
            None,
            "El IaC no declara bases de datos ni grupos de autoescalado: no hay mecanismos de"
            " resiliencia que evaluar.",
        )

    ha = [e for e in señales if e.value.get("mecanismo") in _ALTA_DISPONIBILIDAD]
    grupos = [e for e in señales if e.value.get("mecanismo") == "autoescalado"]
    citadas = [e.id for e in señales]

    con_ha = [e for e in ha if e.value.get("habilitado") is True]
    sin_ha = [e for e in ha if e.value.get("habilitado") is False]
    elasticos = [e for e in grupos if e.value.get("habilitado") is True]

    def _refs(items: list[EvidenceInstance]) -> str:
        return ", ".join(sorted(e.subject_ref for e in items))

    if con_ha and elasticos:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            f"Alta disponibilidad declarada ({_refs(con_ha)}) y capacidad elastica"
            f" ({_refs(elasticos)}): el servicio sobrevive a la perdida de una zona y puede crecer"
            " con la carga.",
            citadas,
        )

    if con_ha:
        detalle = (
            f"los grupos de autoescalado declarados no pueden crecer ({_refs(grupos)})"
            if grupos
            else "no hay ningun grupo de autoescalado"
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            f"Alta disponibilidad declarada ({_refs(con_ha)}), pero {detalle}: PR.IR-04 pide"
            " capacidad adecuada, no solo supervivencia.",
            citadas,
        )

    if elasticos and not sin_ha:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            f"Capacidad elastica declarada ({_refs(elasticos)}), pero ninguna base declara"
            " `multi_az` ni es replica. Crecer con la carga no es sobrevivir a una zona caida.",
            citadas,
        )

    if elasticos and sin_ha:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            25,
            f"Hay capacidad elastica ({_refs(elasticos)}), pero la alta disponibilidad esta"
            f" explicitamente desactivada ({_refs(sin_ha)}: `multi_az = false`).",
            citadas,
        )

    if sin_ha:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            0,
            f"La alta disponibilidad esta explicitamente desactivada ({_refs(sin_ha)}:"
            " `multi_az = false`) y no hay capacidad elastica declarada.",
            citadas,
        )

    return result(
        CRITERION_ID,
        Estado.EVIDENCIA_INSUFICIENTE,
        None,
        "Hay recursos con mecanismos de resiliencia posibles, pero ninguno los declara de forma"
        " literal. Que el `.tf` calle no prueba que falten: el defecto de AWS no se supone.",
        citadas,
    )
