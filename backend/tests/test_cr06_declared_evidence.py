"""CR-06: evidencia declarada que ahora se consume, y expresiones sin resolver (`unresolved`)."""

from datetime import UTC, datetime

from app.adapters.terraform.adapter import TerraformAdapter
from app.evaluation.rules import (
    de01_monitoring,
    pr01_encryption,
    pr03_admin_access,
    pr04_ssh_hardening,
    pr05_public_access,
    pr06_logging,
)
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _parse(tmp_path, hcl: str) -> list[EvidenceInstance]:
    tf_file = tmp_path / "main.tf"
    tf_file.write_text(hcl)
    return TerraformAdapter(source_id="test:cr06", scope="entorno:produccion").parse_path(tf_file)


def _of(evidence, type_id):
    return [e for e in evidence if e.type_id == type_id]


def _ansible(type_id: str, ref: str, value: dict) -> EvidenceInstance:
    return EvidenceInstance(
        type_id=type_id,
        type_version=1,
        subject_type="file",
        subject_ref=ref,
        scope="entorno:produccion",
        value=value,
        source_id="test:cr06",
        locator=Locator(file="play.yml"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="ansible",
    )


# -- adaptador: tf.expression.unresolved -----------------------------------------------


def test_rds_expression_is_unresolved_not_absent(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_db_instance" "db" {
          storage_encrypted       = var.encrypt
          backup_retention_period = var.retention
        }
        """,
    )
    assert _of(evidence, "tf.encryption.config")[0].value["estado"] == "unknown"
    assert "expresion_no_resuelta" in _of(evidence, "tf.encryption.config")[0].limitations
    assert _of(evidence, "tf.backup.config")[0].value["retencion_dias"] is None
    unresolved = _of(evidence, "tf.expression.unresolved")
    assert {e.value["atributo"] for e in unresolved} == {
        "storage_encrypted",
        "backup_retention_period",
    }
    assert all(e.value["recurso"] == "aws_db_instance.db" for e in unresolved)


def test_literal_values_emit_no_unresolved(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_db_instance" "db" {
          storage_encrypted       = true
          backup_retention_period = 7
        }
        """,
    )
    assert _of(evidence, "tf.expression.unresolved") == []


def test_unresolvable_bucket_reference_is_reported(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_s3_bucket" "a" { bucket = "a" }
        resource "aws_s3_bucket_public_access_block" "pab" {
          bucket                  = module.storage.bucket_id
          block_public_acls       = true
          block_public_policy     = true
          ignore_public_acls      = true
          restrict_public_buckets = true
        }
        """,
    )
    unresolved = _of(evidence, "tf.expression.unresolved")
    assert [e.value["atributo"] for e in unresolved] == ["bucket"]
    assert _of(evidence, "tf.public_access.config") == []


def test_security_group_cidr_expression_does_not_crash_nor_invent_a_cidr(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_security_group" "sg" {
          ingress {
            from_port   = 22
            to_port     = 22
            protocol    = "tcp"
            cidr_blocks = var.admin_cidrs
          }
          ingress {
            from_port   = 443
            to_port     = 443
            protocol    = "tcp"
            cidr_blocks = ["10.0.0.0/16", var.extra]
          }
        }
        """,
    )
    rules = _of(evidence, "tf.security_group.rules")[0].value
    assert [r["cidr"] for r in rules] == ["10.0.0.0/16"]
    atributos = [e.value["atributo"] for e in _of(evidence, "tf.expression.unresolved")]
    assert atributos.count("cidr_blocks") == 2


def test_cloudtrail_enable_logging_expression_is_unknown_not_true(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_cloudtrail" "t" {
          name           = "t"
          enable_logging = var.logging
        }
        """,
    )
    assert _of(evidence, "tf.logging.config")[0].value["habilitado"] == "unknown"


# -- reglas: la limitacion se declara y no se inventa un puntaje --------------------------


def test_rule_notes_unresolved_expressions_and_scores_only_the_resolved(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_db_instance" "ok"  { storage_encrypted = true }
        resource "aws_db_instance" "var" { storage_encrypted = var.enc }
        """,
    )
    resultado = pr01_encryption.evaluate(evidence)
    assert resultado.final_score == 100
    assert "Limitacion" in resultado.explanation
    assert "aws_db_instance.var.storage_encrypted" in resultado.explanation


def test_rule_without_unresolved_has_no_limitation_note(tmp_path):
    evidence = _parse(tmp_path, 'resource "aws_db_instance" "ok" { storage_encrypted = true }')
    assert "Limitacion" not in pr01_encryption.evaluate(evidence).explanation


def test_pr06_and_de01_do_not_score_zero_for_unknown_cloudtrail(tmp_path):
    evidence = _parse(
        tmp_path,
        'resource "aws_cloudtrail" "t" { enable_logging = var.logging }',
    )
    for modulo in (pr06_logging, de01_monitoring):
        resultado = modulo.evaluate(evidence)
        assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE
        assert resultado.final_score is None


def test_pr03_still_flags_literal_open_admin_port_next_to_an_expression(tmp_path):
    evidence = _parse(
        tmp_path,
        """
        resource "aws_security_group" "sg" {
          ingress {
            from_port   = 22
            to_port     = 22
            protocol    = "tcp"
            cidr_blocks = ["0.0.0.0/0", var.other]
          }
        }
        """,
    )
    resultado = pr03_admin_access.evaluate(evidence)
    assert resultado.final_score == 25
    assert "Limitacion" in resultado.explanation


def test_pr05_reports_missing_versioning_without_changing_the_score(tmp_path):
    base = """
    resource "aws_s3_bucket" "a" { bucket = "a" }
    resource "aws_s3_bucket_public_access_block" "pab" {
      bucket                  = aws_s3_bucket.a.id
      block_public_acls       = true
      block_public_policy     = true
      ignore_public_acls      = true
      restrict_public_buckets = true
    }
    """
    sin = pr05_public_access.evaluate(_parse(tmp_path, base))
    assert sin.final_score == 100
    assert "versionado" not in sin.explanation  # sin recurso de versionado no hay evidencia

    con = _parse(
        tmp_path,
        base
        + """
        resource "aws_s3_bucket_versioning" "v" {
          bucket = aws_s3_bucket.a.id
          versioning_configuration { status = "Suspended" }
        }
        """,
    )
    resultado = pr05_public_access.evaluate(con)
    assert resultado.final_score == 100
    assert "aws_s3_bucket.a" in resultado.explanation and "versionado" in resultado.explanation


# -- PR-04: an.file.permissions -------------------------------------------------------------


def _sshd_task() -> EvidenceInstance:
    return _ansible(
        "an.task.config",
        "hardening",
        {
            "modulo": "lineinfile",
            "parametros": {
                "path": "/etc/ssh/sshd_config",
                "regexp": "^PermitRootLogin",
                "line": "PermitRootLogin no",
            },
            "tarea": "hardening",
            "archivo": "play.yml",
        },
    )


def _perm(modo: str) -> EvidenceInstance:
    ruta = "/etc/ssh/sshd_config"
    return _ansible("an.file.permissions", ruta, {"ruta": ruta, "modo": modo})


def test_pr04_world_writable_sshd_config_caps_score():
    evidence = [
        _sshd_task(),
        _perm("0666"),
    ]
    resultado = pr04_ssh_hardening.evaluate(evidence)
    assert resultado.final_score == 25
    assert "permisos" in resultado.explanation


def test_pr04_strict_permissions_do_not_change_score():
    base = pr04_ssh_hardening.evaluate([_sshd_task()])
    con = pr04_ssh_hardening.evaluate(
        [
            _sshd_task(),
            _perm("0600"),
        ]
    )
    assert con.final_score == base.final_score


# -- PR-01: policy_exists no eleva ----------------------------------------------------------


def test_pr01_policy_never_raises_score_but_is_cited_next_to_a_gap(tmp_path):
    claim = EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": "policy_exists",
            "contenido": {},
            "encontrado": True,
            "confianza": 0.9,
        },
        source_id="test:cr06",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )
    gap = _parse(tmp_path, 'resource "aws_db_instance" "d" { storage_encrypted = false }')
    resultado = pr01_encryption.evaluate([*gap, claim])
    assert resultado.final_score == 25
    assert claim.id in resultado.evidence_ids

    ok = _parse(tmp_path, 'resource "aws_db_instance" "d" { storage_encrypted = true }')
    assert pr01_encryption.evaluate([*ok, claim]).final_score == 100


def test_de01_cites_observation_window_without_changing_score():
    from tests.test_cr05_docclaim_criteria import _window

    syslog = _ansible(
        "an.service.state", "rsyslog", {"servicio": "rsyslog", "estado": "habilitado"}
    )
    sin = de01_monitoring.evaluate([syslog])
    con = de01_monitoring.evaluate([syslog, _window()])
    assert sin.final_score == con.final_score
    assert "Actividad observable" in con.explanation
