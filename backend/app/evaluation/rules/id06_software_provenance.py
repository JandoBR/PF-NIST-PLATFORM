"""CRI-ID-06 - Procedencia e integridad del software adquirido (ID.RA-09, docs/03).

`ID.RA-09` pide evaluar la autenticidad e integridad del hardware y software **antes** de
adquirirlo y usarlo. En una plataforma descrita con Terraform, lo que se adquiere es codigo: modulos
de terceros y proveedores. La unica forma determinista de afirmar que esa adquisicion esta
controlada es que su procedencia este **fijada** -- un modulo del registry con `version`, uno de git
con `?ref=<tag|sha>`, un proveedor con restriccion en `required_providers`. Sin fijarla, lo que se
despliega manana puede no ser lo que se reviso hoy, y la revision no vale nada.

Dos decisiones que la rubrica hace explicitas:

- **Un modulo local no se penaliza.** `source = "../modules/red"` es codigo del mismo repositorio:
  no se adquiere de nadie y no hay version que fijar. Contarlo como "sin fijar" castigaria tener el
  codigo propio ordenado en modulos.
- **El piso es 25, no 0.** Un `source` sin `version` no es una negacion: es silencio sobre la
  procedencia, el mismo razonamiento del silencio documental (docs/09 §60). Para dar 0 haria falta
  una declaracion explicita de que no se controla, y en HCL eso no existe.
"""

from __future__ import annotations

from app.evaluation.rules._common import by_type, result
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-ID-06"

#: Origenes que son una adquisicion a un tercero. `local` es codigo propio; `desconocido` es un
#: `source` que el parser no pudo leer, y se trata como externo: no se puede suponer que sea propio.
_ORIGENES_EXTERNOS = frozenset({"registry", "git", "externo", "desconocido"})


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    modulos = by_type(evidence, "tf.module.source")
    proveedores = by_type(evidence, "tf.provider.version")

    if not modulos and not proveedores:
        return result(
            CRITERION_ID,
            Estado.NO_APLICABLE,
            None,
            "El modulo no declara bloques `module` ni `required_providers`: no hay procedencia de"
            " software de terceros que evaluar.",
        )

    externos = [m for m in modulos if m.value.get("origen") in _ORIGENES_EXTERNOS]
    externos_sin_fijar = [m for m in externos if not m.value.get("fijada")]
    proveedores_sin_fijar = [p for p in proveedores if not p.value.get("fijada")]

    propios = len(modulos) - len(externos)
    citadas = [e.id for e in (*modulos, *proveedores)]
    inventario = (
        f"{len(externos)} modulo(s) de terceros"
        + (f" y {propios} propio(s)" if propios else "")
        + f", {len(proveedores)} proveedor(es) declarado(s)."
    )

    proveedores_fijados = bool(proveedores) and not proveedores_sin_fijar
    externos_fijados = not externos_sin_fijar

    if proveedores_fijados and externos_fijados:
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            100,
            f"Toda la procedencia esta fijada: {inventario} Cada modulo de terceros declara su"
            " version (o un `ref` en el `source`) y cada proveedor su restriccion.",
            citadas,
        )

    if proveedores_fijados and not externos_fijados:
        nombres = ", ".join(sorted(m.value["nombre"] for m in externos_sin_fijar))
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            75,
            f"Los proveedores estan fijados, pero {len(externos_sin_fijar)} modulo(s) de terceros"
            f" no: {nombres}. {inventario} Un modulo sin fijar puede cambiar entre dos `terraform"
            " init` sin que el codigo del repositorio cambie.",
            citadas,
        )

    if externos_fijados:
        detalle = (
            "ningun proveedor declara restriccion de version"
            if proveedores
            else "no hay `required_providers`"
        )
        return result(
            CRITERION_ID,
            Estado.EVALUADO,
            50,
            f"Los modulos de terceros estan fijados, pero {detalle}. {inventario} El proveedor"
            " es la dependencia que mas superficie aporta: dejarlo libre deja abierta la mayor.",
            citadas,
        )

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        25,
        f"La procedencia del codigo de terceros no esta fijada por ningun lado:"
        f" {len(externos_sin_fijar)} modulo(s) y {len(proveedores_sin_fijar)} proveedor(es) sin"
        f" restriccion. {inventario}",
        citadas,
    )
