from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.methodology.loader import Methodology
from app.methodology.schemas import CriterionDefinition, MethodologySettings
from app.models.tables import Assessment


def build(methodology: Methodology) -> dict[str, Any]:
    return {
        "version_criterios": methodology.version_criterios,
        "version_tipos": methodology.version_tipos,
        "version_csf": methodology.nucleo_csf.version,
        "criterios": [
            criterion.model_dump(mode="json") for criterion in methodology.criterios.values()
        ],
        "settings": methodology.settings.model_dump(mode="json"),
    }


def restore(data: dict[str, Any], current: Methodology) -> Methodology:
    criteria = {item["id"]: CriterionDefinition.model_validate(item) for item in data["criterios"]}
    nucleo = current.nucleo_csf
    if nucleo.version != data["version_csf"]:
        nucleo = replace(nucleo, version=data["version_csf"])
    return Methodology(
        version_criterios=data["version_criterios"],
        version_tipos=data["version_tipos"],
        criterios=criteria,
        tipos_evidencia=current.tipos_evidencia,
        settings=MethodologySettings.model_validate(data["settings"]),
        nucleo_csf=nucleo,
    )


def for_assessment(assessment: Assessment, current: Methodology) -> Methodology:
    data = (assessment.reproducibility or {}).get("methodology")
    if not isinstance(data, dict):
        return current
    try:
        return restore(data, current)
    except (KeyError, TypeError, ValueError):
        return current
