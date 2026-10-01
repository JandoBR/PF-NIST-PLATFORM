"""Adaptador de Ansible: YAML -> evidencias `an.*` (docs/02 §3.2).

Alcance declarado: modulos `lineinfile`, `copy`, `template` (solo rutas), `file`, `service`,
`ufw`/`iptables` (parametros basicos). Cualquier otro modulo (incluye `command`/`shell`) produce
`an.task.uninterpreted` con el motivo. Nunca se ejecuta ningun playbook ni comando (docs/02 §3.2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.schemas.evidence import EvidenceInstance, Locator, Modality

_SUPPORTED_MODULES = {"lineinfile", "copy", "template", "file", "service", "ufw", "iptables"}

#: Claves de control de una tarea, nunca el modulo en si (docs/02 §3.2: alcance declarado).
_CONTROL_KEYS = {
    "name",
    "when",
    "tags",
    "register",
    "notify",
    "become",
    "become_user",
    "vars",
    "loop",
    "with_items",
    "with_dict",
    "ignore_errors",
    "changed_when",
    "failed_when",
    "delegate_to",
    "import_tasks",
    "include_tasks",
}


def _module_key(task: dict) -> tuple[str, str] | None:
    """(modulo_corto, clave_original) de la primera clave de modulo soportada; None si no hay."""

    for key in task:
        if key in _CONTROL_KEYS:
            continue
        short = key.rsplit(".", 1)[-1]
        if short in _SUPPORTED_MODULES:
            return short, key
    return None


def _any_module_key(task: dict) -> str | None:
    """Cualquier clave que no sea de control, soportada o no (para `an.task.uninterpreted`)."""

    for key in task:
        if key not in _CONTROL_KEYS:
            return key
    return None


class AnsibleAdapter:
    """Convierte uno o mas playbooks YAML en instancias de evidencia normalizadas."""

    def __init__(self, source_id: str, scope: str, created_by: str = "adapter:ansible") -> None:
        self.source_id = source_id
        self.scope = scope
        self.created_by = created_by
        self._observed_at = datetime.now(UTC)

    @staticmethod
    def list_files(path: Path) -> list[Path]:
        path = Path(path)
        if path.is_dir():
            return sorted({*path.glob("*.yml"), *path.glob("*.yaml")})
        return [path]

    def parse_path(self, path: Path) -> list[EvidenceInstance]:
        evidence: list[EvidenceInstance] = []
        for file_path in self.list_files(path):
            evidence.extend(self._parse_file(file_path))
        return evidence

    def _parse_file(self, file_path: Path) -> list[EvidenceInstance]:
        with file_path.open("r", encoding="utf-8") as fh:
            plays = yaml.safe_load(fh)
        if not isinstance(plays, list):
            return []

        evidence = [self._playbook_present(file_path, plays)]
        for play in plays:
            if not isinstance(play, dict):
                continue
            for task in play.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                evidence.extend(self._evidence_for_task(file_path, task))
        return evidence

    def _playbook_present(self, file_path: Path, plays: list) -> EvidenceInstance:
        hosts = [p.get("hosts") for p in plays if isinstance(p, dict) and p.get("hosts")]
        return self._make_evidence(
            type_id="an.playbook.present",
            subject_type="playbook",
            subject_ref=file_path.stem,
            value={"archivo": str(file_path), "plays": len(plays), "hosts": hosts},
            file_path=file_path,
        )

    def _evidence_for_task(self, file_path: Path, task: dict) -> list[EvidenceInstance]:
        tarea = task.get("name", "<sin nombre>")
        found = _module_key(task)

        if found is None:
            other_key = _any_module_key(task)
            if other_key is None:
                return []  # tarea solo con claves de control (ej. import_tasks): nada que evaluar
            return [
                self._make_evidence(
                    type_id="an.task.uninterpreted",
                    subject_type="task",
                    subject_ref=tarea,
                    value={"tarea": tarea, "motivo": f"modulo no soportado: {other_key}"},
                    file_path=file_path,
                )
            ]

        modulo, original_key = found
        parametros = task[original_key] or {}
        if not isinstance(parametros, dict):
            parametros = {"valor": parametros}

        if modulo == "file":
            return self._file_permissions(file_path, tarea, parametros)
        if modulo == "service":
            return [self._service_state(file_path, tarea, parametros)]
        return [self._task_config(file_path, tarea, modulo, parametros)]

    def _task_config(
        self, file_path: Path, tarea: str, modulo: str, parametros: dict[str, Any]
    ) -> EvidenceInstance:
        return self._make_evidence(
            type_id="an.task.config",
            subject_type="task",
            subject_ref=tarea,
            value={
                "modulo": modulo,
                "parametros": parametros,
                "tarea": tarea,
                "archivo": str(file_path),
            },
            file_path=file_path,
        )

    def _file_permissions(
        self, file_path: Path, tarea: str, parametros: dict[str, Any]
    ) -> list[EvidenceInstance]:
        ruta = parametros.get("path") or parametros.get("dest")
        modo = parametros.get("mode")
        if ruta is None or modo is None:
            return [self._task_config(file_path, tarea, "file", parametros)]
        return [
            self._make_evidence(
                type_id="an.file.permissions",
                subject_type="file",
                subject_ref=ruta,
                value={"ruta": ruta, "modo": str(modo), "owner": parametros.get("owner")},
                file_path=file_path,
            )
        ]

    def _service_state(
        self, file_path: Path, tarea: str, parametros: dict[str, Any]
    ) -> EvidenceInstance:
        servicio = parametros.get("name", "")
        enabled = parametros.get("enabled")
        state = parametros.get("state")
        if enabled is True or state in ("started", "running"):
            estado = "habilitado"
        elif enabled is False or state in ("stopped",):
            estado = "deshabilitado"
        else:
            estado = "desconocido"
        return self._make_evidence(
            type_id="an.service.state",
            subject_type="service",
            subject_ref=servicio,
            value={"servicio": servicio, "estado": estado},
            file_path=file_path,
        )

    def _make_evidence(
        self,
        *,
        type_id: str,
        subject_type: str,
        subject_ref: str,
        value: Any,
        file_path: Path,
        limitations: str | None = None,
    ) -> EvidenceInstance:
        return EvidenceInstance(
            type_id=type_id,
            type_version=1,
            subject_type=subject_type,
            subject_ref=subject_ref,
            scope=self.scope,
            value=value,
            source_id=self.source_id,
            locator=Locator(file=str(file_path)),
            observed_at=self._observed_at,
            modality=Modality.DECLARADA,
            limitations=limitations,
            created_by=self.created_by,
        )
