"""Carga y valida los catalogos de methodology/*.yml (fallo rapido, docs/04 §8)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.methodology import coverage
from app.methodology.coverage import CoberturaImplementacion
from app.methodology.schemas import (
    CriteriaCatalog,
    CriterionDefinition,
    CsfCoreCatalog,
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
    nucleo_csf: CsfCoreCatalog

    @property
    def methodology_version(self) -> str:
        return (
            f"criterios={self.version_criterios},"
            f"tipos={self.version_tipos},"
            f"settings={self.settings.version},"
            f"csf={self.nucleo_csf.version}"
        )

    def tipos_afirmacion_requeridos(self) -> list[str]:
        """Union de `regla.tipos_afirmacion` de todos los criterios (para U1, docs/05 §2)."""

        tipos: set[str] = set()
        for criterio in self.criterios.values():
            tipos.update(criterio.regla.get("tipos_afirmacion", []))
        return sorted(tipos)

    def cobertura_implementacion(self) -> CoberturaImplementacion:
        """Que parte del nucleo de CSF 2.0 cubre el catalogo (AMP-04, docs/01 §7).

        Metadato del producto, no de una evaluacion: no depende de evidencia ni mueve puntajes.
        """

        return coverage.compute(self.criterios, self.nucleo_csf)


def _read_yaml(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise MethodologyError(f"No se pudo leer {path}: {exc}") from exc


def load_methodology(methodology_dir: Path) -> Methodology:
    """Carga criteria.yml, evidence_types.yml, settings.yml y csf_subcategories.yml."""

    methodology_dir = Path(methodology_dir)

    try:
        criteria_raw = CriteriaCatalog.model_validate(_read_yaml(methodology_dir / "criteria.yml"))
        tipos_raw = EvidenceTypesCatalog.model_validate(
            _read_yaml(methodology_dir / "evidence_types.yml")
        )
        settings = MethodologySettings.model_validate(_read_yaml(methodology_dir / "settings.yml"))
        nucleo_csf = CsfCoreCatalog.model_validate(
            _read_yaml(methodology_dir / "csf_subcategories.yml")
        )
    except ValidationError as exc:
        raise MethodologyError(f"Metodologia invalida: {exc}") from exc

    criterios = {c.id: c for c in criteria_raw.criterios}
    tipos_evidencia = {f"{t.id}@{t.version}": t for t in tipos_raw.tipos}

    _validate_cross_references(criterios, tipos_evidencia, nucleo_csf)

    return Methodology(
        version_criterios=criteria_raw.version,
        version_tipos=tipos_raw.version,
        criterios=criterios,
        tipos_evidencia=tipos_evidencia,
        settings=settings,
        nucleo_csf=nucleo_csf,
    )


def _validate_cross_references(
    criterios: dict[str, CriterionDefinition],
    tipos_evidencia: dict[str, EvidenceTypeDefinition],
    nucleo_csf: CsfCoreCatalog,
) -> None:
    """Las referencias de un criterio deben existir: tipos de evidencia y nucleo de NIST.

    El mapeo a NIST se escribe a mano en `criteria.yml` y hasta ahora nadie lo comprobaba:
    una subcategoria inexistente se cargaba en silencio y falseaba la cobertura. Aqui falla
    el arranque, que es el unico momento en que el error es barato.
    """

    for criterio in criterios.values():
        for evidencia_ref in criterio.evidencias:
            if evidencia_ref not in tipos_evidencia:
                raise MethodologyError(
                    f"{criterio.id} referencia el tipo de evidencia desconocido '{evidencia_ref}'"
                )

        for categoria in criterio.categorias:
            if categoria not in nucleo_csf.categoria_ids:
                raise MethodologyError(
                    f"{criterio.id} referencia la categoria CSF desconocida '{categoria}'"
                )
            if not categoria.startswith(f"{criterio.funcion}."):
                raise MethodologyError(
                    f"{criterio.id} (funcion {criterio.funcion}) declara la categoria"
                    f" '{categoria}', que pertenece a otra funcion"
                )

        for subcategoria in criterio.subcategorias:
            if subcategoria not in nucleo_csf.subcategoria_ids:
                raise MethodologyError(
                    f"{criterio.id} referencia la subcategoria CSF desconocida '{subcategoria}'"
                )
            categoria_padre = subcategoria.rsplit("-", 1)[0]
            if categoria_padre not in criterio.categorias:
                raise MethodologyError(
                    f"{criterio.id} declara la subcategoria '{subcategoria}' pero no lista su"
                    f" categoria '{categoria_padre}' en `categorias`"
                )
