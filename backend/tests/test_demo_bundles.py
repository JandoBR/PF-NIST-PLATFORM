"""Los paquetes de ejemplo de la UI (`frontend/public/demo`) producen lo que su descripcion promete.

Fija los puntajes tecnicos (Terraform + Ansible, sin IA) de cada paquete y los incidentes que abre
cada log, para que un cambio de reglas no deje la demo contando otra historia sin que nadie lo
note. Lo documental depende del modelo y no se fija aqui."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.ansible.adapter import AnsibleAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation import aggregation, engine
from app.evaluation.schemas import Estado
from app.ops.triggers import evaluate_triggers
from app.recommendations.findings import derive_findings
from app.surveillance.events import load_events_jsonl
from app.surveillance.patterns import detect_patterns

DEMO = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"
INSUFICIENTE = Estado.EVIDENCIA_INSUFICIENTE.value

#: Puntaje (o "evidencia_insuficiente") de cada criterio tecnico, por paquete.
ESPERADO = {
    "gaps": {
        "CRI-ID-06": 25,  # dos modulos de git sin `?ref=` y sin required_providers
        "CRI-PR-01": 25,  # una base cifrada y otra no
        "CRI-PR-02": 25,  # una base sin backups y otra con 3 dias
        "CRI-PR-03": 0,  # SSH y RDP abiertos a Internet
        "CRI-PR-04": 25,  # PermitRootLogin yes
        "CRI-PR-05": 0,  # base publica y bucket con un flag en false
        "CRI-PR-06": INSUFICIENTE,
        "CRI-PR-08": 0,  # politica de contrasenas de 6 caracteres declarada en el IaC
        "CRI-DE-01": INSUFICIENTE,
    },
    "mid": {
        "CRI-ID-06": 50,  # el modulo del registry esta fijado, el proveedor no
        "CRI-PR-01": 25,  # la base de reportes sigue sin cifrar
        "CRI-PR-02": 75,  # 14 dias; sin leer la politica (IA) el tope es 75
        "CRI-PR-03": 100,
        "CRI-PR-04": 25,  # root deshabilitado, contrasena todavia permitida
        "CRI-PR-05": INSUFICIENTE,  # el bucket de exportes no tiene bloque
        "CRI-PR-06": 75,  # CloudTrail de una sola region
        "CRI-PR-08": 25,  # 10 caracteres: por debajo de los 14 del CIS AWS
        "CRI-DE-01": 75,
    },
    "good": {
        "CRI-ID-06": 100,  # proveedor y modulo del registry fijados
        "CRI-PR-01": 100,
        "CRI-PR-02": 75,  # 100 cuando la IA lee la politica de 7 dias
        "CRI-PR-03": 100,
        "CRI-PR-04": 100,
        "CRI-PR-05": 50,  # bloqueo parcial en el bucket de logs
        "CRI-PR-06": 100,
        "CRI-PR-08": 100,  # 14 caracteres y una politica que exige MFA
        "CRI-DE-01": 100,
    },
}


def _evaluate(methodology, paquete: str):
    evidence = [
        *TerraformAdapter("demo", "s").parse_path(DEMO / paquete / "terraform"),
        *AnsibleAdapter("demo", "s").parse_path(DEMO / paquete / "ansible"),
    ]
    return evidence, engine.evaluate_all(methodology, evidence)


@pytest.mark.parametrize("paquete", sorted(ESPERADO))
def test_bundle_technical_scores(methodology, paquete):
    _, results = _evaluate(methodology, paquete)
    obtenido = {
        r.criterion_id: r.final_score if r.final_score is not None else r.estado.value
        for r in results
        if r.criterion_id in ESPERADO[paquete]
    }
    assert obtenido == ESPERADO[paquete]


def test_bundles_are_a_progression(methodology):
    def global_score(paquete: str) -> float:
        _, results = _evaluate(methodology, paquete)
        funciones = aggregation.aggregate_by_funcion(methodology, results)
        return aggregation.aggregate_global(methodology, funciones).score

    gaps, mid, good = (global_score(p) for p in ("gaps", "mid", "good"))
    assert gaps < mid < good
    assert gaps > 10 and good < 100  # ningun extremo es todo ceros ni todo perfecto


def test_bundles_show_every_severity_between_them(methodology):
    def severidades(paquete: str) -> set[str]:
        _, results = _evaluate(methodology, paquete)
        return {f.severidad for f in derive_findings(methodology, results)}

    assert severidades("gaps") == {"alta", "media"}
    # `baja` aparece en mid desde CRI-ID-06 (50): el modulo esta fijado y el proveedor no.
    assert severidades("mid") == {"baja", "media"}
    assert severidades("good") == {"baja"}


def test_mid_bundle_exercises_cross_file_references_and_a_limitation(methodology):
    evidence, results = _evaluate(methodology, "mid")
    # El bloque de `documentos` esta en security.tf y el bucket en main.tf: se resuelve.
    assert [e.subject_ref for e in evidence if e.type_id == "tf.public_access.config"] == [
        "aws_s3_bucket.documentos"
    ]
    limitaciones = [
        f for f in derive_findings(methodology, results, evidence) if f.tipo == "limitacion"
    ]
    assert [f.criterion_id for f in limitaciones] == [
        "CRI-PR-03"
    ]  # cidr_blocks = var.partner_cidrs


@pytest.mark.parametrize(
    ("log", "disparadores"),
    [
        ("incidentes-demo", ["D1", "D3", "D4"]),
        ("respuesta-parcial-demo", ["D3", "D5"]),
        ("flujo-correcto-demo", []),
    ],
)
def test_event_log_opens_the_incidents_it_describes(methodology, log, disparadores):
    eventos = load_events_jsonl(DEMO / "events" / f"{log}.jsonl")
    patrones = detect_patterns(eventos, methodology.settings.vigilancia)
    triggers = evaluate_triggers(patrones, methodology.settings.vigilancia, "entorno:produccion")
    assert [t.disparador for t in triggers] == disparadores
