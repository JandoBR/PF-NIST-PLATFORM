"""CRI-GV-05 — Contexto organizacional (docs/03 §1).

Documental (`doc.claim(tipo=org_context)`). GV.OC tiene cinco resultados distintos y cada uno es un
campo del contenido, para que la declaracion de cada subcategoria dependa de que ese dato venga y
no del criterio entero:

- `mision` -> GV.OC-01 · `partes_interesadas` -> GV.OC-02 · `requisitos_legales` -> GV.OC-03
- `servicios_criticos` -> GV.OC-04 · `dependencias` -> GV.OC-05

El puntaje es proporcional a cuantos de los cinco se declaran, y la explicacion nombra los que
faltan: la lista es el valor de este criterio, no un numero suelto.
"""

from __future__ import annotations

from app.evaluation.rules._common import (
    doc_claims,
    found,
    merged_content,
    result,
    silencio_documental,
)
from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

CRITERION_ID = "CRI-GV-05"
CRITERION_VERSION = 1

#: Campo del contenido -> que resultado del CSF sostiene. El orden es el de GV.OC.
_CAMPOS: dict[str, str] = {
    "mision": "mision (GV.OC-01)",
    "partes_interesadas": "partes interesadas (GV.OC-02)",
    "requisitos_legales": "requisitos legales (GV.OC-03)",
    "servicios_criticos": "servicios criticos (GV.OC-04)",
    "dependencias": "dependencias externas (GV.OC-05)",
}


def evaluate(evidence: list[EvidenceInstance]) -> CriterionResult:
    claims = doc_claims(evidence, "org_context")
    if not claims:
        return result(
            CRITERION_ID,
            Estado.EVIDENCIA_INSUFICIENTE,
            None,
            "Sin documentos analizados (o sin afirmaciones utilizables) sobre el contexto"
            " organizacional.",
        )

    encontradas = found(claims)
    if not encontradas:
        return silencio_documental(
            CRITERION_ID,
            "Los documentos analizados no declaran el contexto organizacional (mision, partes"
            " interesadas, requisitos legales, servicios criticos ni dependencias).",
            [c.id for c in claims],
        )

    contenido, aportantes = merged_content(encontradas)
    declarados = [c for c in _CAMPOS if contenido.get(c) not in (None, "", [], {}, False)]
    faltantes = [_CAMPOS[c] for c in _CAMPOS if c not in declarados]

    if not declarados:
        return silencio_documental(
            CRITERION_ID,
            "La afirmacion de contexto no trae ninguno de los cinco datos de GV.OC.",
            [c.id for c in encontradas],
        )

    detalle = f" Falta declarar: {', '.join(faltantes)}." if faltantes else ""
    if len(declarados) == 5:
        score = 100
        resumen = "Contexto organizacional completo: los cinco resultados de GV.OC declarados."
    elif len(declarados) >= 3:
        score = 75
        resumen = f"Contexto organizacional declarado en {len(declarados)} de 5 resultados."
    else:
        score = 50
        resumen = f"Contexto organizacional apenas esbozado ({len(declarados)} de 5 resultados)."

    return result(
        CRITERION_ID,
        Estado.EVALUADO,
        score,
        resumen + detalle,
        [c.id for c in aportantes],
    )
