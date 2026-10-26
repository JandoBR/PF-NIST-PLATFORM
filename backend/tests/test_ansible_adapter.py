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


def test_service_state_wins_over_enabled(tmp_path):
    """`state` describe el estado actual; `enabled` solo dice si arranca al boot."""

    playbook = tmp_path / "services.yml"
    playbook.write_text(
        """
- hosts: all
  tasks:
    - name: Detenido pero habilitado al boot
      service:
        name: rsyslog
        state: stopped
        enabled: true

    - name: Reiniciado
      service:
        name: syslog-ng
        state: restarted
""",
        encoding="utf-8",
    )
    evidence = AnsibleAdapter(source_id="test:svc", scope="s").parse_path(playbook)
    estados = {
        e.value["servicio"]: e.value["estado"] for e in _by_type(evidence, "an.service.state")
    }
    assert estados == {"rsyslog": "deshabilitado", "syslog-ng": "habilitado"}


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


def test_vault_unsafe_and_yaml_scalars_do_not_crash(tmp_path):
    playbook = tmp_path / "tags.yml"
    playbook.write_text(
        """
- hosts: [web, db]
  vars:
    db_password: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      616263
  tasks:
    - name: Endurecer SSH
      lineinfile:
        path: /etc/ssh/sshd_config
        line: !unsafe "PermitRootLogin no"

    - name: Fecha sin comillas
      lineinfile:
        path: /etc/ssh/sshd_config
        line: 2025-01-01
""",
        encoding="utf-8",
    )
    evidence = AnsibleAdapter(source_id="test:tags", scope="s").parse_path(playbook)

    playbook_ev = _by_type(evidence, "an.playbook.present")[0]
    assert playbook_ev.value["hosts"] == ["web", "db"]
    lineas = {
        t.value["parametros"]["line"]
        for t in _by_type(evidence, "an.task.config")
        if "line" in t.value["parametros"]
    }
    assert lineas == {"PermitRootLogin no", "2025-01-01"}


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
