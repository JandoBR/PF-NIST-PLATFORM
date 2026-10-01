from pathlib import Path

from app.adapters.ansible.adapter import AnsibleAdapter

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ansible"


def _by_type(evidence, type_id):
    return [e for e in evidence if e.type_id == type_id]


def test_good_fixture_detects_ssh_hardening_and_rsyslog():
    adapter = AnsibleAdapter(source_id="test:good", scope="entorno:produccion")
    evidence = adapter.parse_path(FIXTURES / "good")

    tasks = _by_type(evidence, "an.task.config")
    sshd_lines = {t.value["parametros"]["line"] for t in tasks if t.value["modulo"] == "lineinfile"}
    assert "PermitRootLogin no" in sshd_lines
    assert "PasswordAuthentication no" in sshd_lines

    permissions = _by_type(evidence, "an.file.permissions")[0]
    assert permissions.value == {"ruta": "/etc/ssh/sshd_config", "modo": "0600", "owner": "root"}

    service = _by_type(evidence, "an.service.state")[0]
    assert service.value == {"servicio": "rsyslog", "estado": "habilitado"}

    playbook = _by_type(evidence, "an.playbook.present")[0]
    assert playbook.value["hosts"] == ["servidores_app"]


def test_gaps_fixture_flags_insecure_directive_and_uninterpreted_command():
    adapter = AnsibleAdapter(source_id="test:gaps", scope="entorno:produccion")
    evidence = adapter.parse_path(FIXTURES / "gaps")

    lineinfile = next(
        t for t in _by_type(evidence, "an.task.config") if t.value["modulo"] == "lineinfile"
    )
    assert lineinfile.value["parametros"]["line"] == "PermitRootLogin yes"

    uninterpreted = _by_type(evidence, "an.task.uninterpreted")[0]
    assert "command" in uninterpreted.value["motivo"]

    service = _by_type(evidence, "an.service.state")[0]
    assert service.value == {"servicio": "ufw", "estado": "deshabilitado"}


def test_task_with_only_control_keys_produces_no_evidence(tmp_path):
    playbook = tmp_path / "noop.yml"
    playbook.write_text(
        """
        - hosts: all
          tasks:
            - name: Importar otras tareas
              import_tasks: otras.yml
        """
    )
    adapter = AnsibleAdapter(source_id="test:noop", scope="s")
    evidence = adapter.parse_path(playbook)

    # solo el an.playbook.present; la tarea en si no produce evidencia evaluable
    assert len(evidence) == 1
    assert evidence[0].type_id == "an.playbook.present"


def test_non_dict_tasks_and_plays_are_ignored(tmp_path):
    playbook = tmp_path / "weird.yml"
    playbook.write_text("- hosts: all\n  tasks: ['no-es-un-dict']\n")

    adapter = AnsibleAdapter(source_id="test:weird", scope="s")
    evidence = adapter.parse_path(playbook)

    assert len(evidence) == 1  # solo an.playbook.present
