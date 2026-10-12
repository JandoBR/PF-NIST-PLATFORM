"""Esquemas de los catalogos versionados en methodology/*.yml (docs/04 §8, docs/01, docs/03)."""

from __future__ import annotations

import re
from enum import StrEnum
from functools import cached_property

from pydantic import BaseModel, Field, model_validator

from app.schemas.evidence import Modality


class CriterionType(StrEnum):
    TECNICO = "tecnico"
    PROCESO = "proceso"
    MIXTO = "mixto"


class EvidenceTypeDefinition(BaseModel):
    id: str
    version: int
    descripcion: str
    valor_schema: dict
    modalidad_permitida: list[Modality]
    requiere_locator: bool = True
    estado: str = "published"
    publicado: str | None = None
    notas: str | None = None


class CriterionDefinition(BaseModel):
    id: str
    version: int
    titulo: str
    tipo: CriterionType
    funcion: str
    categorias: list[str]
    subcategorias: list[str]
    peso: int
    ai_adjustable: bool
    evidencias: list[str]
    recomendacion: str
    regla: dict


class IASettings(BaseModel):
    alpha: float
    divergencia_maxima: float
    umbral_confianza_documental: float
    #: Tope de criterios que U2 puede ajustar por evaluacion (control de costo/tiempo, docs/05 §3).
    #: `None` = sin limite. Si hay mas candidatos, se ajustan los de mayor peso (desempate por id);
    #: el resto conserva S = B sin marcarse `degradado` (no se intento).
    max_criterios_ajustados_por_evaluacion: int | None = None


class TierSettings(BaseModel):
    t2: dict[str, float]
    t3: dict[str, float]
    t4: dict[str, float]


class PlanesSettings(BaseModel):
    #: Un criterio con `final_score` por debajo de esto genera un hallazgo/plan (docs/05 §4).
    umbral_brecha: float = 75.0


class CoberturaSettings(BaseModel):
    """Un puntaje con cobertura por debajo de este umbral se marca `provisional` (docs/01 §7):
    el promedio solo describe los criterios con evidencia suficiente, no la organizacion."""

    umbral_provisional: float = 0.5


class AuthFailuresBurstSettings(BaseModel):
    n: int = 5
    ventana_minutos: int = 5


class VigilanciaSettings(BaseModel):
    """Umbrales de disparadores (docs/08 §5: "N, W y plazos vienen de la metodologia, no del
    modelo"). `auth_failures_burst` alimenta D1; `plazo_triaje_minutos` alimenta D2;
    `plazo_escalamiento_minutos` alimenta D3."""

    auth_failures_burst: AuthFailuresBurstSettings = Field(
        default_factory=AuthFailuresBurstSettings
    )
    plazo_escalamiento_minutos: int = 30
    plazo_triaje_minutos: int = 30
    #: Cuantos `log.pattern` nuevos (evidencia que consume la madurez) debe agregar una ingesta
    #: para disparar una reevaluacion automatica del org+scope. Reingerir el mismo archivo agrega
    #: 0 y no dispara. Default 3 = "cambio considerable"; configurable en settings.yml.
    refresco_min_patrones_nuevos: int = 3


class MethodologySettings(BaseModel):
    version: int
    ia: IASettings
    tier: TierSettings
    funciones: dict[str, float]
    planes: PlanesSettings = Field(default_factory=PlanesSettings)
    cobertura: CoberturaSettings = Field(default_factory=CoberturaSettings)
    vigilancia: VigilanciaSettings = Field(default_factory=VigilanciaSettings)


class EvidenceTypesCatalog(BaseModel):
    version: int
    tipos: list[EvidenceTypeDefinition]


class CriteriaCatalog(BaseModel):
    version: int
    criterios: list[CriterionDefinition]


class CsfSubcategory(BaseModel):
    id: str
    titulo: str


class CsfCategory(BaseModel):
    id: str
    nombre: str
    subcategorias: list[CsfSubcategory]


class CsfFunction(BaseModel):
    id: str
    nombre: str
    categorias: list[CsfCategory]


class CsfCoreCatalog(BaseModel):
    """Nucleo de NIST CSF 2.0: el denominador de la cobertura de implementacion (docs/01 §7).

    Las invariantes de abajo son lo que convierte un id mal escrito en un fallo de arranque
    en vez de en una subcategoria fantasma: `subcategorias` en un criterio es `list[str]`
    sin validar, asi que el unico sitio donde se puede atrapar el error es aqui.
    """

    version: int
    total_declarado: int
    funciones: list[CsfFunction]

    @model_validator(mode="after")
    def _check_estructura(self) -> CsfCoreCatalog:
        vistos: set[str] = set()
        for funcion in self.funciones:
            for categoria in funcion.categorias:
                if not categoria.id.startswith(f"{funcion.id}."):
                    raise ValueError(
                        f"la categoria '{categoria.id}' no pertenece a la funcion '{funcion.id}'"
                    )
                for sub in categoria.subcategorias:
                    if not sub.id.startswith(f"{categoria.id}-"):
                        raise ValueError(
                            f"la subcategoria '{sub.id}' no pertenece a la categoria"
                            f" '{categoria.id}'"
                        )
                    if not re.fullmatch(r".+-\d{2}", sub.id):
                        raise ValueError(f"la subcategoria '{sub.id}' no termina en -NN")
                    if sub.id in vistos:
                        raise ValueError(f"la subcategoria '{sub.id}' esta duplicada")
                    vistos.add(sub.id)

        # Los huecos de numeracion de CSF 2.0 son reales; este conteo impide "rellenarlos".
        if len(vistos) != self.total_declarado:
            raise ValueError(
                f"el catalogo declara {self.total_declarado} subcategorias pero contiene"
                f" {len(vistos)}"
            )
        return self

    @cached_property
    def subcategoria_ids(self) -> frozenset[str]:
        return frozenset(
            sub.id
            for funcion in self.funciones
            for categoria in funcion.categorias
            for sub in categoria.subcategorias
        )

    @cached_property
    def categoria_ids(self) -> frozenset[str]:
        return frozenset(
            categoria.id for funcion in self.funciones for categoria in funcion.categorias
        )
