"""OP-15: la evidencia de Terraform y Ansible apunta a las lineas exactas del archivo."""

from app.adapters.ansible.adapter import AnsibleAdapter
from app.adapters.terraform.adapter import TerraformAdapter, resource_line_ranges


def _terraform(tmp_path, texto):
    archivo = tmp_path / "main.tf"
    archivo.write_text(texto)
    return TerraformAdapter(source_id="s", scope="entorno:produccion").parse_path(archivo)


def test_resource_line_ranges_handles_nesting_strings_and_comments():
    texto = (
        'provider "aws" {}\n'  # 1
        "\n"  # 2
        'resource "aws_db_instance" "a" {\n'  # 3
        "  tags = {\n"  # 4
        '    nota = "una llave } dentro de un string"\n'  # 5
        "  }  # llave } en un comentario\n"  # 6
        "}\n"  # 7
        'resource "aws_s3_bucket" "b" { bucket = "x" }\n'  # 8
    )

    assert resource_line_ranges(texto) == {
        ("aws_db_instance", "a"): (3, 7),
        ("aws_s3_bucket", "b"): (8, 8),
    }


def test_line_ranges_ignore_block_comments_and_heredocs_and_accept_next_line_brace():
    texto = (
        "/* comentario con } */\n"  # 1
        'resource "aws_s3_bucket" "b" {\n'  # 2
        "  description = <<EOF\n"  # 3
        "  } esto no cierra el bloque\n"  # 4
        "EOF\n"  # 5
        "}\n"  # 6
        "\n"  # 7
        'resource "aws_db_instance" "d"\n'  # 8
        "{\n"  # 9
        "  storage_encrypted = true\n"  # 10
        "}\n"  # 11
    )

    assert resource_line_ranges(texto) == {
        ("aws_s3_bucket", "b"): (2, 6),
        ("aws_db_instance", "d"): (8, 11),
    }


def test_an_unclosed_block_extends_to_the_end_of_the_file():
    assert resource_line_ranges('resource "aws_s3_bucket" "b" {\n  bucket = "x"\n') == {
        ("aws_s3_bucket", "b"): (1, 2)
    }


def test_terraform_evidence_carries_the_resource_lines(tmp_path):
    evidence = _terraform(
        tmp_path,
        'resource "aws_db_instance" "db" {\n  storage_encrypted = false\n}\n\n'
        'resource "aws_cloudtrail" "t" {\n  enable_logging = true\n}\n',
    )

    por_recurso = {
        e.subject_ref: (e.locator.line_start, e.locator.line_end)
        for e in evidence
        if e.type_id in {"tf.encryption.config", "tf.logging.config"}
    }
    assert por_recurso["aws_db_instance.db"] == (1, 3)
    assert por_recurso["aws_cloudtrail.t"] == (5, 7)


def test_an_unsupported_resource_declares_the_limitation(tmp_path):
    evidence = _terraform(
        tmp_path,
        'resource "aws_lambda_function" "f" {\n  runtime = "python3.12"\n}\n\n'
        'resource "aws_s3_bucket" "b" {\n  bucket = "x"\n}\n',
    )

    presencia = {e.subject_ref: e for e in evidence if e.type_id == "tf.resource.present"}
    assert "no soportado" in presencia["aws_lambda_function.f"].limitations
    assert presencia["aws_lambda_function.f"].locator.line_start == 1
    assert presencia["aws_s3_bucket.b"].limitations is None


def test_ansible_tasks_carry_their_own_lines(tmp_path):
    playbook = tmp_path / "p.yml"
    playbook.write_text(
        "- hosts: all\n"  # 1
        "  tasks:\n"  # 2
        "    - name: uno\n"  # 3
        "      service:\n"  # 4
        "        name: rsyslog\n"  # 5
        "        state: started\n"  # 6
        "\n"  # 7
        "    # comentario suelto\n"  # 8
        "    - name: dos\n"  # 9
        "      shell: echo hola\n"  # 10
    )

    evidence = AnsibleAdapter(source_id="s", scope="entorno:produccion").parse_path(playbook)

    lineas = {
        e.value.get("servicio") or e.value.get("tarea"): (e.locator.line_start, e.locator.line_end)
        for e in evidence
        if e.type_id in {"an.service.state", "an.task.uninterpreted"}
    }
    assert lineas == {"rsyslog": (3, 6), "dos": (9, 10)}
    presente = next(e for e in evidence if e.type_id == "an.playbook.present")
    assert presente.locator.line_start is None  # el playbook es el archivo entero
