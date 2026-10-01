from datetime import UTC, datetime

from app.evaluation.rules import pr04_ssh_hardening
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality

LOCATOR = Locator(file="hardening.yml")


def _lineinfile(line: str, regexp: str = "") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="an.task.config",
        type_version=1,
        subject_type="task",
        subject_ref="tarea",
        scope="entorno:produccion",
        value={
            "modulo": "lineinfile",
            "parametros": {"path": "/etc/ssh/sshd_config", "regexp": regexp, "line": line},
            "tarea": "tarea",
            "archivo": "hardening.yml",
        },
        source_id="test:ansible",
        locator=LOCATOR,
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="adapter:ansible",
    )


def test_no_sshd_tasks_is_insufficient():
    result = pr04_ssh_hardening.evaluate([])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE


def test_both_directives_hardened_scores_100():
    claims = [_lineinfile("PermitRootLogin no"), _lineinfile("PasswordAuthentication no")]
    result = pr04_ssh_hardening.evaluate(claims)
    assert result.final_score == 100


def test_only_one_directive_hardened_scores_75():
    claims = [_lineinfile("PermitRootLogin no")]
    result = pr04_ssh_hardening.evaluate(claims)
    assert result.final_score == 75


def test_neither_directive_mentioned_scores_50():
    claims = [_lineinfile("Port 2222")]
    result = pr04_ssh_hardening.evaluate(claims)
    assert result.final_score == 50


def test_explicit_insecure_directive_scores_25_even_if_other_is_hardened():
    claims = [_lineinfile("PermitRootLogin yes"), _lineinfile("PasswordAuthentication no")]
    result = pr04_ssh_hardening.evaluate(claims)
    assert result.final_score == 25


def test_non_sshd_lineinfile_tasks_are_ignored():
    other = _lineinfile("PermitRootLogin no")
    other.value["parametros"]["path"] = "/etc/other.conf"
    result = pr04_ssh_hardening.evaluate([other])
    assert result.estado == Estado.EVIDENCIA_INSUFICIENTE
