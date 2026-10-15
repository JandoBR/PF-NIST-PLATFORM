"""Utilidades de golden files (docs/07 §3, docs/11 TS-01).

Un golden file es la salida esperada, versionada en git, de correr el codigo real sobre un fixture
fijo. Aqui se normaliza lo que cambia en cada corrida (ids uuid, `observed_at`, rutas absolutas)
para que el diff solo muestre cambios reales de comportamiento.

Para regenerar tras un cambio intencional y revisar el diff en git:

    UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.evaluation.schemas import Aggregate, CriterionResult
from app.schemas.evidence import EvidenceInstance

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_TOKEN = "<REPO>"


def _label(item: EvidenceInstance) -> str:
    return f"{item.type_id}|{item.subject_ref}"


def _portable_paths(node: Any) -> Any:
    """Rutas absolutas bajo el repo -> `<REPO>/...` con separador `/`.

    Los adaptadores registran el archivo fuente con ruta absoluta, que cambia con la máquina y
    rompe los goldens fuera del checkout canónico. Solo se tocan cadenas que empiezan por la raíz
    del repo; el resto (regex, valores de configuración) queda intacto.
    """

    if isinstance(node, str):
        root = str(REPO_ROOT)
        if node == root or node.startswith(root + os.sep):
            return REPO_TOKEN + node[len(root) :].replace(os.sep, "/")
        return node
    if isinstance(node, dict):
        return {k: _portable_paths(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_portable_paths(v) for v in node]
    return node


def normalize_evidence(evidence: list[EvidenceInstance]) -> list[dict[str, Any]]:
    """Sin `id`, `observed_at` ni `source_id` (varian por corrida); `locator.file` solo el nombre
    del archivo; rutas absolutas bajo el repo como `<REPO>/...` (portable entre maquinas);
    orden estable."""

    items = []
    for e in evidence:
        locator = {k: v for k, v in e.locator.model_dump().items() if v is not None}
        if "file" in locator:
            locator["file"] = Path(locator["file"]).name
        items.append(
            _portable_paths(
                {
                    "type_id": e.type_id,
                    "type_version": e.type_version,
                    "subject_type": e.subject_type,
                    "subject_ref": e.subject_ref,
                    "scope": e.scope,
                    "value": e.value,
                    "locator": locator,
                    "modality": e.modality.value,
                    "limitations": e.limitations,
                    "created_by": e.created_by,
                }
            )
        )
    return sorted(
        items,
        key=lambda i: (i["type_id"], i["subject_ref"], json.dumps(i["value"], sort_keys=True)),
    )


def normalize_results(
    results: list[CriterionResult], evidence: list[EvidenceInstance]
) -> list[dict[str, Any]]:
    """`evidence_ids` (uuid) se reemplaza por etiquetas `tipo|sujeto`, estables entre corridas."""

    labels = {e.id: _label(e) for e in evidence}
    return [
        {
            "criterion_id": r.criterion_id,
            "estado": r.estado.value,
            "base_score": r.base_score,
            "final_score": r.final_score,
            "explanation": r.explanation,
            "evidence": sorted(labels.get(i, "?") for i in r.evidence_ids),
        }
        for r in sorted(results, key=lambda r: r.criterion_id)
    ]


def normalize_aggregate(aggregate: Aggregate) -> dict[str, Any]:
    return aggregate.model_dump(mode="json")


def assert_matches_golden(name: str, actual: Any) -> None:
    """Compara `actual` con `tests/golden/<name>.json`; con `UPDATE_GOLDEN=1` lo reescribe."""

    path = GOLDEN_DIR / f"{name}.json"
    rendered = json.dumps(actual, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return

    assert path.exists(), (
        f"Falta el golden file {path.name}. Generalo con UPDATE_GOLDEN=1 y revisa el diff en git."
    )
    expected = path.read_text(encoding="utf-8")
    assert rendered == expected, (
        f"{path.name} difiere de la salida actual. Si el cambio es intencional, regeneralo con"
        " UPDATE_GOLDEN=1 y revisa el diff; si no, es una regresion."
    )
