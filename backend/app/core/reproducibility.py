"""Metadatos de reproducibilidad por evaluacion (docs/01 §10, docs/11 OP-14).

Guarda con que se calculo una evaluacion mas alla de `methodology_version`: version de cada
adaptador y de la libreria que parsea, y -- solo si la IA realmente participo -- el modelo y la
version de prompt de cada paso. Asi dos corridas distintas sobre las mismas fuentes se pueden
explicar ("cambio el modelo", "cambio el prompt de extraccion").

`ADAPTER_VERSION` de cada adaptador se sube a mano cuando cambia lo que emite.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.adapters.ansible.adapter import ADAPTER_VERSION as ANSIBLE_ADAPTER_VERSION
from app.adapters.documents.adapter import ADAPTER_VERSION as DOCUMENTS_ADAPTER_VERSION
from app.adapters.terraform.adapter import ADAPTER_VERSION as TERRAFORM_ADAPTER_VERSION
from app.ai import adjustment, extraction, plan_generation
from app.ai.client import AIClient, NullAIClient
from app.ai.store import store_for
from app.methodology import snapshot
from app.methodology.loader import Methodology


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def model_name(client: AIClient | None) -> str | None:
    """Modelo del cliente real, atravesando el envoltorio de cache. `None` si no hay IA."""

    while client is not None:
        if isinstance(client, NullAIClient):
            return None
        modelo = getattr(client, "model", None)
        if isinstance(modelo, str):
            return modelo
        client = getattr(client, "_inner", None)
    return None


def _ai_active(client: AIClient | None) -> bool:
    return client is not None and not isinstance(client, NullAIClient)


def build(
    *,
    methodology: Methodology,
    terraform: bool,
    ansible: bool,
    documents: bool,
    ai_client: AIClient | None,
    ai_adjustment: bool,
) -> dict[str, Any]:
    adapters: dict[str, Any] = {}
    if terraform:
        adapters["terraform"] = {
            "adapter": TERRAFORM_ADAPTER_VERSION,
            "parser": f"python-hcl2 {_package_version('python-hcl2')}",
        }
    if ansible:
        adapters["ansible"] = {
            "adapter": ANSIBLE_ADAPTER_VERSION,
            "parser": f"PyYAML {_package_version('PyYAML')}",
        }
    if documents:
        adapters["documents"] = {"adapter": DOCUMENTS_ADAPTER_VERSION}

    ai: dict[str, Any] | None = None
    if _ai_active(ai_client):
        pasos: dict[str, str] = {}
        if documents:
            pasos["extraccion"] = extraction.PROMPT_VERSION
        if ai_adjustment:
            pasos["ajuste"] = adjustment.PROMPT_VERSION
        if pasos:
            ai = {"modelo": model_name(ai_client), **pasos}
    return {"adapters": adapters, "ai": ai, "methodology": snapshot.build(methodology)}


def with_methodology(info: dict[str, Any] | None, methodology: Methodology) -> dict[str, Any]:
    result = dict(info or {"adapters": {}, "ai": None})
    result["methodology"] = snapshot.build(methodology)
    return result


def with_eventos(info: dict[str, Any] | None, eventos: dict[str, Any]) -> dict[str, Any]:
    """Anota que eventos operativos consumio la evaluacion (seleccion, rango y hash)."""

    result = dict(info or {"adapters": {}, "ai": None})
    result["eventos"] = eventos
    return result


def with_plans_ai(info: dict[str, Any] | None, ai_client: AIClient | None) -> dict[str, Any] | None:
    """Anota que los planes se redactaron con IA (U3) en un `reproducibility` existente."""

    if not _ai_active(ai_client):
        return info
    info = dict(info or {"adapters": {}, "ai": None})
    ai = dict(info.get("ai") or {"modelo": model_name(ai_client)})
    ai["planes"] = plan_generation.PROMPT_VERSION
    info["ai"] = ai
    return info


def with_ai_cache(info: dict[str, Any] | None, ai_client: AIClient | None) -> dict[str, Any] | None:
    """Anota el uso del store de IA: hits/misses por paso, votos de U1 y hash de parametros.

    Se llama al terminar el pipeline (y otra vez tras generar planes con IA), porque las
    estadisticas son del cliente y solo estan completas cuando ya corrieron U1/U2/U3 (docs/01 §10).
    """

    store = store_for(ai_client)
    if store is None:
        return info
    info = dict(info or {"adapters": {}, "ai": None})
    ai = dict(info.get("ai") or {"modelo": store.model})
    ai["cache"] = store.stats()
    ai["votos"] = store.votes
    ai["params_hash"] = store.params_hash
    info["ai"] = ai
    return info
