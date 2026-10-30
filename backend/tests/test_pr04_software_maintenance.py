"""CRI-PR-04 v2: mantener el software al dia como compuerta del 100 (PR.PS-02, docs/09 §94)."""

from __future__ import annotations

import pytest

from app.adapters.ansible.adapter import AnsibleAdapter
from app.evaluation.rules import pr04_ssh_hardening as regla
from app.evaluation.schemas import Estado

_SSH_ENDURECIDO = (
    "    - lineinfile:\n"
    "        path: /etc/ssh/sshd_config\n"
    "        line: 'PermitRootLogin no'\n"
    "    - lineinfile:\n"
    "        path: /etc/ssh/sshd_config\n"
    "        line: 'PasswordAuthentication no'\n"
)


def _evaluar(tmp_path, tareas: str):
    playbook = "- hosts: all\n  become: true\n  tasks:\n" + tareas
    (tmp_path / "p.yml").write_text(playbook, encoding="utf-8")
    evidencia = AnsibleAdapter(source_id="s", scope="entorno:produccion").parse_path(tmp_path)
    return regla.evaluate(evidencia), evidencia


# -- lectura de la intencion ------------------------------------------------------


@pytest.mark.parametrize(
    ("tarea", "intencion"),
    [
        ("    - apt:\n        upgrade: safe\n", "actualiza"),
        ("    - apt:\n        name: nginx\n        state: latest\n", "actualiza"),
        ("    - apt:\n        name: nginx\n        state: present\n", "instala"),
        ("    - yum:\n        name: nginx\n", "instala"),
        ("    - apt:\n        name: telnet\n        state: absent\n", "elimina"),
        ("    - package:\n        name: nginx\n        state: latest\n", "actualiza"),
    ],
)
def test_the_intent_of_a_package_task_is_read(tmp_path, tarea, intencion):
    _, evidencia = _evaluar(tmp_path, tarea)
    señal = next(e for e in evidencia if e.type_id == "an.package.state")

    assert señal.value["intencion"] == intencion


def test_a_package_module_is_no_longer_uninterpreted(tmp_path):
    """Antes de la Oleada C, `apt` caia en `an.task.uninterpreted` y se perdia la señal."""

    _, evidencia = _evaluar(tmp_path, "    - apt:\n        upgrade: safe\n")

    assert [e for e in evidencia if e.type_id == "an.task.uninterpreted"] == []
    assert [e.type_id for e in evidencia if e.type_id == "an.package.state"] == ["an.package.state"]


# -- la compuerta del 100 ---------------------------------------------------------


def test_hardened_ssh_without_patching_stays_at_75(tmp_path):
    resultado, _ = _evaluar(tmp_path, _SSH_ENDURECIDO)

    assert (resultado.estado, resultado.final_score) == (Estado.EVALUADO, 75)
    assert "PR.PS-02" in resultado.explanation


def test_hardened_ssh_plus_an_upgrade_task_reaches_100(tmp_path):
    resultado, _ = _evaluar(
        tmp_path,
        _SSH_ENDURECIDO + "    - apt:\n        upgrade: safe\n        update_cache: true\n",
    )

    assert resultado.final_score == 100


def test_installing_a_package_is_not_maintaining_it(tmp_path):
    """`state: present` deja la version que ya hubiera instalada: no mantiene nada."""

    resultado, _ = _evaluar(
        tmp_path, _SSH_ENDURECIDO + "    - apt:\n        name: telegraf\n        state: present\n"
    )

    assert resultado.final_score == 75
    assert "solo instalan o eliminan" in resultado.explanation


def test_an_insecure_directive_still_dominates(tmp_path):
    """Si el SSH no esta endurecido, ese es el problema: la compuerta no toca el tramo bajo."""

    tareas = (
        "    - lineinfile:\n"
        "        path: /etc/ssh/sshd_config\n"
        "        line: 'PermitRootLogin yes'\n"
        "    - apt:\n        upgrade: safe\n"
    )
    resultado, _ = _evaluar(tmp_path, tareas)

    assert resultado.final_score == 25


def test_the_permissions_cap_is_applied_before_the_gate(tmp_path):
    """Un sshd_config escribible por otros topa en 25 aunque el sistema este al dia."""

    tareas = (
        _SSH_ENDURECIDO
        + "    - file:\n        path: /etc/ssh/sshd_config\n        mode: '0666'\n"
        + "    - apt:\n        upgrade: safe\n"
    )
    resultado, _ = _evaluar(tmp_path, tareas)

    assert resultado.final_score == 25
    assert "puntaje maximo 25" in resultado.explanation
