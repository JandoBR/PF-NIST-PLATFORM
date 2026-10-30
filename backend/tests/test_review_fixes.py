"""Regresiones de la revision de bugs (docs/09 §65): cada test reproduce un error que la suite no
cubria. Usan los adaptadores reales sobre archivos temporales."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.adapters.ansible.adapter import AnsibleAdapter
from app.adapters.terraform.adapter import TerraformAdapter
from app.core import assessment_service as svc
from app.core import jobs as job_service
from app.core import operations
from app.evaluation import engine
from app.evaluation.rules import (
    id01_asset_inventory,
    pr01_encryption,
    pr02_backup,
    pr04_ssh_hardening,
    pr05_public_access,
)
from app.evaluation.schemas import Estado
from app.models.tables import CriterionResultRow, Incident, LogPatternRow, PlanRow
from app.recommendations.findings import derive_findings
from app.schemas.evidence import EvidenceInstance, Locator, Modality
from app.surveillance.events import RawEvent
from app.surveillance.patterns import detect_patterns
from app.workers import core as worker_core

DEMO = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"
SCOPE = "entorno:produccion"


def _tf(tmp_path: Path, **archivos: str) -> list[EvidenceInstance]:
    for nombre, texto in archivos.items():
        (tmp_path / f"{nombre}.tf").write_text(texto, encoding="utf-8")
    return TerraformAdapter("test", "s").parse_path(tmp_path)


def _ansible(tmp_path: Path, tareas: str) -> list[EvidenceInstance]:
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(f"- hosts: all\n  tasks:\n{tareas}", encoding="utf-8")
    return AnsibleAdapter("test", "s").parse_path(playbook)


def _claim(tipo: str, contenido: dict) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=2,
        subject_type="document",
        subject_ref="doc:politica",
        scope="s",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido,
            "encontrado": True,
            "confianza": 0.9,
        },
        source_id="test",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


_SSH_NO = """    - lineinfile:
        path: /etc/ssh/sshd_config
        line: 'PermitRootLogin no'
    - lineinfile:
        path: /etc/ssh/sshd_config
        line: 'PasswordAuthentication no'
"""


# -- pisos de las reglas tecnicas: ausencia explicita = 0, parcial = 25 ------------------------


def test_pr01_no_resource_encrypted_is_0_but_a_mix_is_25(tmp_path):
    sin_cifrar = 'resource "aws_db_instance" "a" {\n  storage_encrypted = false\n}\n'
    cifrada = 'resource "aws_db_instance" "b" {\n  storage_encrypted = true\n}\n'

    assert pr01_encryption.evaluate(_tf(tmp_path, a=sin_cifrar)).final_score == 0
    assert pr01_encryption.evaluate(_tf(tmp_path, a=sin_cifrar, b=cifrada)).final_score == 25


def test_pr02_no_database_with_backups_is_0_but_a_mix_is_25(tmp_path):
    sin_backup = 'resource "aws_db_instance" "a" {\n  backup_retention_period = 0\n}\n'
    con_backup = 'resource "aws_db_instance" "b" {\n  backup_retention_period = 14\n}\n'

    assert pr02_backup.evaluate(_tf(tmp_path, a=sin_backup)).final_score == 0
    assert pr02_backup.evaluate(_tf(tmp_path, a=sin_backup, b=con_backup)).final_score == 25


def test_pr04_both_directives_insecure_is_0_and_one_is_25(tmp_path):
    def score(root: str, password: str) -> float | None:
        tareas = (
            "    - lineinfile:\n        path: /etc/ssh/sshd_config\n"
            f"        line: 'PermitRootLogin {root}'\n"
            "    - lineinfile:\n        path: /etc/ssh/sshd_config\n"
            f"        line: 'PasswordAuthentication {password}'\n"
        )
        return pr04_ssh_hardening.evaluate(_ansible(tmp_path, tareas)).final_score

    assert score("yes", "yes") == 0
    assert score("yes", "no") == 25


def test_open_admin_ports_and_missing_encryption_are_high_severity(methodology):
    """El motivo del cambio: con el piso en 25, SSH abierto a Internet o una base sin cifrar
    nunca llegaban a severidad alta, y un solo flag de S3 en false si."""

    evidence = TerraformAdapter("test", "s").parse_path(FIXTURES / "gaps")
    results = engine.evaluate_all(methodology, evidence)
    severidad = {
        f.criterion_id: f.severidad
        for f in derive_findings(methodology, results)
        if f.tipo == "brecha"
    }
    assert {severidad[c] for c in ("CRI-PR-01", "CRI-PR-02", "CRI-PR-03", "CRI-PR-05")} == {"alta"}


# -- ID-01: los recursos de configuracion no son activos ----------------------------------------


def test_id01_complete_inventory_scores_100():
    evidence = TerraformAdapter("test", "s").parse_path(FIXTURES / "good")
    inventario = _claim(
        "data_inventory",
        {
            "activos": [
                "aws_db_instance",
                "aws_s3_bucket",
                "aws_security_group",
                "aws_cloudtrail",
                # La Oleada C añadio identidades al fixture: un inventario completo las lista.
                "aws_iam_role",
                "aws_iam_policy",
            ]
        },
    )
    result = id01_asset_inventory.evaluate([*evidence, inventario])
    assert result.final_score == 100 and "(6/6)" in result.explanation


# -- Ansible: modo octal sin comillas -----------------------------------------------------------


@pytest.mark.parametrize(
    ("modo", "esperado", "score"),
    [
        ("0644", "0644", 100),  # antes: "420" -> leido como octal -> "escritura para grupo" -> 25
        ("0600", "0600", 100),  # antes: "384" -> octal invalido -> se ignoraba
        ('"0644"', "0644", 100),
        ("0666", "0666", 25),  # este si es inseguro
    ],
)
def test_ansible_unquoted_octal_mode_is_read_as_octal(tmp_path, modo, esperado, score):
    tareas = _SSH_NO + f"    - file:\n        path: /etc/ssh/sshd_config\n        mode: {modo}\n"
    evidence = _ansible(tmp_path, tareas)

    (permisos,) = [e for e in evidence if e.type_id == "an.file.permissions"]
    assert permisos.value["modo"] == esperado
    assert pr04_ssh_hardening.evaluate(evidence).final_score == score


# -- PR-04: el valor sale de `line`, no de `regexp` ---------------------------------------------


def test_pr04_ignores_the_regexp_when_reading_the_value(tmp_path):
    tareas = """    - lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^PermitRootLogin (yes|no)'
        line: 'PermitRootLogin yes'
    - lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^PasswordAuthentication (yes|no)'
        line: 'PasswordAuthentication no'
"""
    result = pr04_ssh_hardening.evaluate(_ansible(tmp_path, tareas))
    assert result.final_score == 25  # antes 100: el "no" del regexp se tomaba como el valor


# -- PR-04: permisos simbolicos -----------------------------------------------------------------


def test_pr04_symbolic_mode_caps_at_25(tmp_path):
    tareas = """
    - name: Permisos
      file:
        path: /etc/ssh/sshd_config
        mode: "u=rw,g=rw,o=rw"
    - name: Root
      lineinfile:
        path: /etc/ssh/sshd_config
        line: "PermitRootLogin no"
    - name: Password
      lineinfile:
        path: /etc/ssh/sshd_config
        line: "PasswordAuthentication no"
"""
    result = pr04_ssh_hardening.evaluate(_ansible(tmp_path, tareas))
    assert result.final_score == 25


def test_pr04_relative_symbolic_mode_is_insufficient(tmp_path):
    tareas = """
    - name: Permisos
      file:
        path: /etc/ssh/sshd_config
        mode: "u+rwx"
    - name: Root
      lineinfile:
        path: /etc/ssh/sshd_config
        line: "PermitRootLogin no"
    - name: Password
      lineinfile:
        path: /etc/ssh/sshd_config
        line: "PasswordAuthentication no"
"""
    result = pr04_ssh_hardening.evaluate(_ansible(tmp_path, tareas))
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


# -- PR-05: un bucket sin bloque declarado no puede dar 100 -------------------------------------

_BLOQUE = """resource "aws_s3_bucket_public_access_block" "a" {
  bucket                  = aws_s3_bucket.a.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
"""


def test_pr05_a_bucket_without_a_block_prevents_the_100(tmp_path):
    buckets = (
        'resource "aws_s3_bucket" "a" {\n  bucket = "a"\n}\n'
        'resource "aws_s3_bucket" "b" {\n  bucket = "b"\n}\n'
    )
    result = pr05_public_access.evaluate(_tf(tmp_path, main=buckets + _BLOQUE))
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert "aws_s3_bucket.b" in result.explanation


# -- Terraform: referencias entre archivos ------------------------------------------------------


def test_pr05_an_unresolved_block_prevents_the_100(tmp_path):
    buckets = (
        'resource "aws_s3_bucket" "a" {\n  bucket = "a"\n}\n'
        'resource "aws_s3_bucket" "b" {\n  bucket = "b"\n}\n'
    )
    bloque_b = """resource "aws_s3_bucket_public_access_block" "b" {
  bucket                  = aws_s3_bucket.b.id
  block_public_acls       = var.block_acls
  block_public_policy     = var.block_policy
  ignore_public_acls      = var.ignore_acls
  restrict_public_buckets = var.restrict_buckets
}
"""
    result = pr05_public_access.evaluate(_tf(tmp_path, main=buckets + _BLOQUE + bloque_b))
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert "aws_s3_bucket.b" in result.explanation


def test_terraform_resolves_a_bucket_declared_in_another_file(tmp_path):
    evidence = _tf(
        tmp_path, storage='resource "aws_s3_bucket" "a" {\n  bucket = "a"\n}\n', security=_BLOQUE
    )
    assert not [e for e in evidence if e.type_id == "tf.expression.unresolved"]
    assert pr05_public_access.evaluate(evidence).final_score == 100


# -- PR-02: unidades de la retencion ------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "dias"),
    [
        ("7 dias", 7),
        ("7d", 7),
        ("30 días", 30),
        ("2 semanas", 14),
        ("1 mes", 30),
        ("6 meses", 180),
        ("1 año", 365),
        ("sin definir", None),
    ],
)
def test_policy_retention_understands_units(texto, dias):
    claim = _claim("backup_policy", {"retencion": texto})
    assert pr02_backup.retencion_politica_dias(claim) == dias


# -- vigilancia: rafaga con ventana deslizante --------------------------------------------------


def _fallo(i: int, momento: datetime) -> RawEvent:
    return RawEvent(
        event_id=f"f{i}",
        event_time=momento,
        tipo="auth_failure",
        recurso="srv",
        scope=SCOPE,
        actor="admin",
    )


def test_a_later_failure_does_not_hide_a_burst(methodology):
    inicio = datetime(2026, 9, 20, 3, 10, tzinfo=UTC)
    rafaga = [_fallo(i, inicio + timedelta(seconds=10 * i)) for i in range(6)]
    suelto = _fallo(99, inicio + timedelta(hours=1))

    (match,) = detect_patterns([*rafaga, suelto], methodology.settings.vigilancia)
    assert match.patron == "auth_failures_burst"
    assert match.conteo == 6 and "f99" not in match.event_ids


def test_spread_out_failures_are_not_a_burst(methodology):
    inicio = datetime(2026, 9, 20, 3, 10, tzinfo=UTC)
    espaciados = [_fallo(i, inicio + timedelta(minutes=10 * i)) for i in range(8)]
    assert detect_patterns(espaciados, methodology.settings.vigilancia) == []


# -- ingesta: los patrones describen todos los eventos del scope --------------------------------


def test_second_log_updates_the_patterns_instead_of_piling_up(db_session, methodology):
    """Antes cada archivo dejaba sus propias filas: tras el log con incidentes y el de flujo
    correcto quedaban dos `auth_failures_burst`, y el `restore_exercise_run` ok se descartaba por
    coincidir en hora con el fallido, asi que RC-02 seguia en 0."""

    eventos = DEMO / "events"
    operations.ingest_events(db_session, methodology, "Org", eventos / "incidentes-demo.jsonl")
    operations.ingest_events(db_session, methodology, "Org", eventos / "flujo-correcto-demo.jsonl")

    patrones = [p.patron for p in db_session.query(LogPatternRow).all()]
    assert len(patrones) == len(set(patrones))  # uno por tipo

    org_id = db_session.query(Incident).first().org_id
    evidence = svc.collect_surveillance_evidence(db_session, org_id, SCOPE)
    results = {r.criterion_id: r for r in engine.evaluate_all(methodology, evidence)}
    assert results["CRI-RC-02"].final_score == 75  # el ultimo ejercicio fue ok y se verifico


def test_unrelated_ingest_leaves_existing_incidents_and_plan_follow_up_alone(
    db_session, methodology, tmp_path
):
    eventos = DEMO / "events"
    primero = operations.ingest_events(
        db_session, methodology, "Org", eventos / "incidentes-demo.jsonl"
    )
    incidente = primero.nuevos_incidentes[0]
    entradas = len(incidente.timeline)
    plan = db_session.query(PlanRow).filter_by(incident_id=incidente.id).one()
    plan.estado = "en_progreso"
    db_session.commit()

    otro = tmp_path / "otro.jsonl"
    otro.write_text(
        '{"event_id": "x-1", "event_time": "2026-09-21T08:00:00Z", "tipo": "login_ok",'
        ' "recurso": "srv-web-09", "scope": "entorno:produccion"}\n'
    )
    segundo = operations.ingest_events(db_session, methodology, "Org", otro)

    assert segundo.nuevos_incidentes == [] and segundo.incidentes_actualizados == []
    db_session.refresh(incidente)
    assert len(incidente.timeline) == entradas
    assert (
        db_session.query(PlanRow).filter_by(incident_id=incidente.id).one().estado == "en_progreso"
    )


# -- workers: un job que ya no esta pendiente no se ejecuta -------------------------------------


def test_worker_does_not_run_a_job_that_was_already_given_up_on(db_session, methodology):
    """El job se dio por perdido mientras hacia cola y el usuario lo reintento: llegan dos
    mensajes para la misma evaluacion. Antes se ejecutaban los dos y duplicaban los resultados."""

    assessment = svc.create_pending_assessment(db_session, methodology, org_name="Org", scope="s")
    mensaje = {
        "assessment_id": assessment.id,
        "terraform_path": str(FIXTURES / "good"),
        "ai_requested": False,
    }
    perdido = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)
    job_service.mark_failed(db_session, perdido, "no fue tomado a tiempo")
    reintento = job_service.create_job(db_session, "assessment_run", assessment_id=assessment.id)

    for job in (perdido, reintento):
        worker_core.process_message(db_session, methodology, {**mensaje, "job_id": job.id})

    db_session.refresh(perdido)
    db_session.refresh(reintento)
    assert (perdido.estado, reintento.estado) == ("fallido", "completado")
    filas = db_session.query(CriterionResultRow).filter_by(assessment_id=assessment.id).count()
    assert filas == len(methodology.criterios)
