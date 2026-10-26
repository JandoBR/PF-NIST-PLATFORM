"""Adaptador de Ansible: YAML -> evidencias `an.*` (docs/02 §3.2).

Alcance declarado: modulos `lineinfile`, `copy`, `template` (solo rutas), `file`, `service`,
`ufw`/`iptables` (parametros basicos). Cualquier otro modulo (incluye `command`/`shell`) produce
`an.task.uninterpreted` con el motivo. Nunca se ejecuta ningun playbook ni comando (docs/02 §3.2).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.schemas.evidence import EvidenceInstance, Locator, Modality


class _AnsibleLoader(yaml.SafeLoader):
    """SafeLoader que acepta los tags de Ansible (`!vault`, `!unsafe`, ...) sin resolverlos.

    `!vault` es un secreto cifrado que el adaptador no necesita descifrar; `!unsafe` es texto
    literal. Cualquier otro tag `!...` se vuelve opaco en vez de tumbar la evaluacion entera.
    """


def _opaque_tag(loader: _AnsibleLoader, tag: str, node: yaml.Node) -> Any:
    if tag == "vault":
        return "<vault>"
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_AnsibleLoader.add_multi_constructor("!", _opaque_tag)


def _json_safe(value: Any) -> Any:
    """Convierte escalares nativos de YAML (fechas) a JSON, sin cambiar str/int/float/bool."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


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


#: Se sube a mano cuando cambia lo que el adaptador emite (docs/11 OP-14).
#: v2: el locator trae `line_start`/`line_end` de la tarea (docs/11 OP-15).
#: v3: `an.file.permissions.modo` es siempre octal, aunque el YAML lo traiga sin comillas.
#: v4: `state` manda sobre `enabled` (un `stopped` no es "habilitado"); `restarted`/`reloaded`
#: cuentan como servicio corriendo.
#: v5: acepta `!vault`/`!unsafe` y otros tags `!...`; normaliza fechas YAML a texto; `hosts`
#: siempre es un array de strings y el BOM UTF-8 no rompe el playbook.
#: v6: traduce modos simbolicos absolutos (`u=rw,g=r`) a octal; los relativos quedan `unknown`.
ADAPTER_VERSION = "6"


_SYMBOLIC_MODE = re.compile(r"^(?:[ugoa]=[rwxXst]*)(?:,(?:[ugoa]=[rwxXst]*))*$")
_MODE_BITS = {
    "u": {"r": 0o400, "w": 0o200, "x": 0o100, "X": 0o100},
    "g": {"r": 0o040, "w": 0o020, "x": 0o010, "X": 0o010},
    "o": {"r": 0o004, "w": 0o002, "x": 0o001, "X": 0o001},
}


def _modo_octal(modo: Any) -> str:
    """El modo como texto octal. YAML lee `mode: 0644` (sin comillas) como el entero 420; tomarlo
    tal cual lo convertia en "420", que leido como octal son otros permisos.

    Los modos simbolicos absolutos (`u=rw,g=r,o=`) se traducen; los relativos (`u+rwx`, que
    dependen de los permisos actuales) quedan como `unknown` y el criterio no puede dar 100.
    """

    if isinstance(modo, int) and not isinstance(modo, bool):
        return format(modo, "04o")
    texto = str(modo).strip()
    if re.fullmatch(r"[0-7]{3,4}", texto):
        return texto.zfill(4)
    if _SYMBOLIC_MODE.fullmatch(texto):
        bits = 0
        for clausula in texto.split(","):
            quien, permisos = clausula.split("=", 1)
            for destino in "ugo" if quien == "a" else quien:
                for permiso in permisos:
                    bits |= _MODE_BITS[destino].get(permiso, 0)
        return format(bits, "04o")
    return "unknown"


def _node_lines(node: yaml.Node, lineas: list[str]) -> tuple[int, int]:
    """Lineas (1-based, inclusivas) que ocupa un nodo YAML.

    PyYAML deja `end_mark` donde empieza el token siguiente, no donde termina el nodo: se retrocede
    hasta la ultima linea con contenido (sin contar blancos ni comentarios sueltos)."""

    inicio = node.start_mark.line
    fin = node.end_mark.line
    antes = lineas[fin][: node.end_mark.column] if fin < len(lineas) else ""
    if fin >= len(lineas) or not antes.strip():
        fin -= 1  # el nodo termina antes de la linea donde empieza el siguiente token
    while fin > inicio and (not lineas[fin].strip() or lineas[fin].lstrip().startswith("#")):
        fin -= 1
    return inicio + 1, max(fin, inicio) + 1


def _task_nodes(root: yaml.Node | None) -> list[list[yaml.Node]]:
    """Por cada play (en el orden del documento), los nodos de sus tareas."""

    if not isinstance(root, yaml.SequenceNode):
        return []
    plays: list[list[yaml.Node]] = []
    for play in root.value:
        tareas: list[yaml.Node] = []
        if isinstance(play, yaml.MappingNode):
            for clave, valor in play.value:
                if clave.value == "tasks" and isinstance(valor, yaml.SequenceNode):
                    tareas = list(valor.value)
        plays.append(tareas)
    return plays


class AnsibleAdapter:
    """Convierte uno o mas playbooks YAML en instancias de evidencia normalizadas."""

    def __init__(self, source_id: str, scope: str, created_by: str = "adapter:ansible") -> None:
        self.source_id = source_id
        self.scope = scope
        self.created_by = created_by
        self._observed_at = datetime.now(UTC)
        #: Lineas de la tarea que se esta procesando; `_make_evidence` las pone en el locator.
        self._lines: tuple[int, int] | None = None

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
        text = file_path.read_text(encoding="utf-8-sig")
        plays = yaml.load(text, Loader=_AnsibleLoader)
        if not isinstance(plays, list):
            return []
        nodos = _task_nodes(yaml.compose(text, Loader=_AnsibleLoader))
        lineas = text.splitlines()

        self._lines = None
        evidence = [self._playbook_present(file_path, plays)]
        for indice, play in enumerate(plays):
            if not isinstance(play, dict):
                continue
            nodos_play = nodos[indice] if indice < len(nodos) else []
            tareas = play.get("tasks") or []
            for posicion, task in enumerate(tareas):
                if not isinstance(task, dict):
                    continue
                coincide = posicion < len(nodos_play) and len(nodos_play) == len(tareas)
                self._lines = _node_lines(nodos_play[posicion], lineas) if coincide else None
                evidence.extend(self._evidence_for_task(file_path, task))
        self._lines = None
        return evidence

    def _playbook_present(self, file_path: Path, plays: list) -> EvidenceInstance:
        # `hosts` es un array de strings en el contrato (docs/02 §3.2); `hosts: [web, db]` no
        # puede quedar anidado como `[["web", "db"]]`.
        hosts: list[str] = []
        for play in plays:
            if not isinstance(play, dict):
                continue
            valor = play.get("hosts")
            if isinstance(valor, list):
                hosts.extend(str(item) for item in valor)
            elif valor:
                hosts.append(str(valor))
        return self._make_evidence(
            type_id="an.playbook.present",
            subject_type="playbook",
            subject_ref=file_path.stem,
            value={"archivo": str(file_path), "plays": len(plays), "hosts": hosts},
            file_path=file_path,
        )

    def _evidence_for_task(self, file_path: Path, task: dict) -> list[EvidenceInstance]:
        tarea = str(task.get("name") or "<sin nombre>")
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
        parametros = _json_safe(task[original_key] or {})
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
        ruta = str(ruta)
        return [
            self._make_evidence(
                type_id="an.file.permissions",
                subject_type="file",
                subject_ref=ruta,
                value={"ruta": ruta, "modo": _modo_octal(modo), "owner": parametros.get("owner")},
                file_path=file_path,
            )
        ]

    def _service_state(
        self, file_path: Path, tarea: str, parametros: dict[str, Any]
    ) -> EvidenceInstance:
        servicio = str(parametros.get("name", ""))
        enabled = parametros.get("enabled")
        state = parametros.get("state")
        # `state` describe el estado actual y manda sobre `enabled` (que solo dice si arranca al
        # boot). Un `state: stopped` no puede volverse "habilitado" porque `enabled: true`.
        if state in ("started", "running", "restarted", "reloaded"):
            estado = "habilitado"
        elif state == "stopped":
            estado = "deshabilitado"
        elif state is not None:
            estado = "desconocido"
        elif enabled is True:
            estado = "habilitado"
        elif enabled is False:
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
            locator=Locator(
                file=str(file_path),
                line_start=self._lines[0] if self._lines else None,
                line_end=self._lines[1] if self._lines else None,
            ),
            observed_at=self._observed_at,
            modality=Modality.DECLARADA,
            limitations=limitations,
            created_by=self.created_by,
        )
