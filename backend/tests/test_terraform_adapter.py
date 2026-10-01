from pathlib import Path

from app.adapters.terraform.adapter import TerraformAdapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terraform"


def _evidence_by_type(evidence, type_id):
    return [e for e in evidence if e.type_id == type_id]


def test_good_fixture_resolves_cross_resource_s3_reference():
    adapter = TerraformAdapter(source_id="test:good", scope="entorno:produccion")
    evidence = adapter.parse_path(FIXTURES / "good")

    encryption = _evidence_by_type(evidence, "tf.encryption.config")
    s3_encryption = next(e for e in encryption if e.subject_type == "aws_s3_bucket")
    assert s3_encryption.subject_ref == "aws_s3_bucket.documentos"
    assert s3_encryption.value == {
        "estado": "enabled",
        "mecanismo": "aws:kms",
        "llave": "alias/aws/s3",
    }

    public_access = _evidence_by_type(evidence, "tf.public_access.config")[0]
    assert public_access.value == {"bloqueo_publico": True, "nivel": "completo"}


def test_good_fixture_security_group_rules_flatten_per_cidr():
    adapter = TerraformAdapter(source_id="test:good", scope="entorno:produccion")
    evidence = adapter.parse_path(FIXTURES / "good")

    rules = _evidence_by_type(evidence, "tf.security_group.rules")[0].value
    assert len(rules) == 3
    ssh_rule = next(r for r in rules if r["puerto_desde"] == 22)
    assert ssh_rule["cidr"] == "10.0.0.0/16"


def test_rds_without_storage_encrypted_is_unknown_not_assumed_false(tmp_path):
    tf_file = tmp_path / "main.tf"
    tf_file.write_text(
        """
        resource "aws_db_instance" "no_attr" {
          identifier = "no-attr-db"
        }
        """
    )
    adapter = TerraformAdapter(source_id="test:unknown", scope="entorno:produccion")
    evidence = adapter.parse_path(tf_file)

    encryption = _evidence_by_type(evidence, "tf.encryption.config")[0]
    assert encryption.value["estado"] == "unknown"
    assert encryption.limitations is not None


def test_gaps_fixture_flags_explicit_disabled_states():
    adapter = TerraformAdapter(source_id="test:gaps", scope="entorno:produccion")
    evidence = adapter.parse_path(FIXTURES / "gaps")

    encryption = _evidence_by_type(evidence, "tf.encryption.config")[0]
    assert encryption.value["estado"] == "disabled"

    backup = _evidence_by_type(evidence, "tf.backup.config")[0]
    assert backup.value == {"retencion_dias": 0, "habilitado": False, "ventana": None}

    public_access = _evidence_by_type(evidence, "tf.public_access.config")[0]
    assert public_access.value == {"bloqueo_publico": False, "nivel": "ninguno"}
