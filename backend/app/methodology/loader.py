"""Carga y valida los catalogos de methodology/*.yml (fallo rapido, docs/04 §8)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.methodology.schemas import (
    CriteriaCatalog,
    CriterionDefinition,
    EvidenceTypeDefinition,
    EvidenceTypesCatalog,
    MethodologySettings,
)


class MethodologyError(Exception):
    """Catalogo invalido: el sistema no debe arrancar con metodologia inconsistente."""


@dataclass(frozen=True)
class Methodology:
    version_criterios: int
    version_tipos: int
    criterios: dict[str, CriterionDefinition]
    tipos_evidencia: dict[str, EvidenceTypeDefinition]
    settings: MethodologySettings

    @property
    def methodology_version(self) -> str:
        return (
            f"criterios={self.version_criterios},"
            f"tipos={self.version_tipos},"
            f"settings={self.settings.version}"
        )

    def tipos_afirmacion_requeridos(self) -> list[str]:
        """Union de `regla.tipos_afirmacion` de todos los criterios (para U1, docs/05 §2)."""

        tipos: set[str] = set()
        for criterio in self.criterios.values():
            tipos.update(criterio.regla.get("tipos_afirmacion", []))
        return sorted(tipos)


def _read_yaml(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise MethodologyError(f"No se pudo leer {path}: {exc}") from exc


def load_methodology(methodology_dir: Path) -> Methodology:
    """Carga criteria.yml, evidence_types.yml y settings.yml validando su esquema."""

    methodology_dir = Path(methodology_dir)

    try:
        criteria_raw = CriteriaCatalog.model_validate(_read_yaml(methodology_dir / "criteria.yml"))
        tipos_raw = EvidenceTypesCatalog.model_validate(
            _read_yaml(methodology_dir / "evidence_types.yml")
        )
        settings = MethodologySettings.model_validate(_read_yaml(methodology_dir / "settings.yml"))
    except ValidationError as exc:
        raise MethodologyError(f"Metodologia invalida: {exc}") from exc

    criterios = {c.id: c for c in criteria_raw.criterios}
    tipos_evidencia = {f"{t.id}@{t.version}": t for t in tipos_raw.tipos}

    _validate_cross_references(criterios, tipos_evidencia)

    return Methodology(
        version_criterios=criteria_raw.version,
        version_tipos=tipos_raw.version,
        criterios=criterios,
        tipos_evidencia=tipos_evidencia,
        settings=settings,
    )


def _validate_cross_references(
    criterios: dict[str, CriterionDefinition],
    tipos_evidencia: dict[str, EvidenceTypeDefinition],
) -> None:
    """Cada evidencia referenciada por un criterio debe existir en el catalogo de tipos."""

    for criterio in criterios.values():
        for evidencia_ref in criterio.evidencias:
            if evidencia_ref not in tipos_evidencia:
                raise MethodologyError(
                    f"{criterio.id} referencia el tipo de evidencia desconocido '{evidencia_ref}'"
                )
