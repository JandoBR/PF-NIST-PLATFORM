"""Adaptador de Terraform: HCL -> evidencias `tf.*` (docs/02 §3.1).

Alcance declarado: `aws_db_instance`, `aws_s3_bucket` (+ sus recursos de configuracion separados
`aws_s3_bucket_server_side_encryption_configuration`, `aws_s3_bucket_public_access_block`,
`aws_s3_bucket_versioning`), `aws_security_group`, `aws_cloudtrail`.

Ademas de los `resource`, lee los bloques `module` y `terraform { required_providers }` para la
procedencia del codigo de terceros (`tf.module.source`, `tf.provider.version`).
Solo parsea; nunca ejecuta Terraform ni resuelve el estado real de la nube (docs/02 §7).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import hcl2
from hcl2.utils import SerializationOptions

from app.schemas.evidence import EvidenceInstance, Locator, Modality

_REF_PATTERN = re.compile(r"^\$\{?([a-zA-Z0-9_]+)\.([a-zA-Z0-9_-]+)(?:\.[a-zA-Z0-9_]+)*\}?$")

_HANDLED_TYPES = {
    "aws_db_instance",
    "aws_s3_bucket",
    "aws_s3_bucket_server_side_encryption_configuration",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_versioning",
    "aws_security_group",
    "aws_cloudtrail",
}


#: Recursos que configuran a otro (el bucket) y no son un activo propio: no van en un inventario.
CONFIG_RESOURCE_TYPES = frozenset(
    {
        "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_versioning",
    }
)


def _resolve_simple_ref(value: Any) -> tuple[str, str] | None:
    """Resuelve una referencia directa a otro recurso local (docs/02 §4: 'variable literal simple').

    Solo resuelve `tipo.nombre` o `${tipo.nombre.attr}`; cualquier otra expresion
    (funcion, for_each, count, modulo) se trata como no resuelta por el caller.
    """

    if not isinstance(value, str):
        return None
    match = _REF_PATTERN.match(value.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


#: Atributos cuyo valor decide un puntaje. Si alguno es una expresion que el parser no resuelve
#: (variable, local, funcion, modulo...), se emite `tf.expression.unresolved` en vez de adivinar
#: (docs/02 §4). `bucket` de los recursos S3 de configuracion se trata aparte (referencia).
_WATCHED_ATTRS: dict[str, set[str]] = {
    "aws_db_instance": {
        "storage_encrypted",
        "kms_key_id",
        "backup_retention_period",
        "backup_window",
        "publicly_accessible",
    },
    "aws_s3_bucket_server_side_encryption_configuration": {
        "sse_algorithm",
        "kms_master_key_id",
    },
    "aws_s3_bucket_public_access_block": {
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    },
    "aws_s3_bucket_versioning": {"status"},
    "aws_security_group": {"cidr_blocks", "ipv6_cidr_blocks", "from_port", "to_port"},
    "aws_cloudtrail": {"enable_logging", "is_multi_region_trail"},
}

_EXPRESSION_REASON = (
    "expresion no resoluble de forma determinista (variable, local, funcion o modulo)"
)


def _is_expression(value: Any) -> bool:
    """`python-hcl2` serializa toda expresion no literal como un string `${...}`."""

    return isinstance(value, str) and "${" in value


def _expressions_in(value: Any) -> list[str]:
    if _is_expression(value):
        return [value]
    if isinstance(value, list):
        return [expr for item in value for expr in _expressions_in(item)]
    return []


def _find_unresolved(obj: Any, watched: set[str]) -> list[tuple[str, str]]:
    """(atributo, expresion) de cada atributo vigilado cuyo valor es una expresion, a cualquier
    profundidad (los atributos de S3/SG viven en bloques anidados)."""

    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in watched:
                found.extend((key, expr) for expr in _expressions_in(value))
            else:
                found.extend(_find_unresolved(value, watched))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_unresolved(item, watched))
    return found


#: Origen/destino de una regla cuyo CIDR es una expresion sin resolver.
CIDR_DESCONOCIDO = "unknown"


def _cidrs(value: Any) -> list[str]:
    """CIDRs de una regla. Uno que es una expresion (o la lista entera) queda como `unknown`, nunca
    como un CIDR inventado ni omitido: una regla de origen desconocido sigue siendo una regla."""

    if _is_expression(value):
        return [CIDR_DESCONOCIDO]
    if not isinstance(value, list):
        return []
    return [CIDR_DESCONOCIDO if _is_expression(item) else item for item in value]


def _block_start(keyword: str, etiquetas: int) -> re.Pattern[str]:
    """Patron que reconoce la linea que abre un bloque `keyword "et1" "et2" {`.

    El `\\b` impide que `terraform` coincida con `terraform_remote_state`, y las etiquetas se
    capturan para usarlas como clave del rango.
    """

    labels = "".join([r'\s+"([^"]+)"'] * etiquetas)
    return re.compile(rf"^\s*{keyword}\b{labels}\s*")


_RESOURCE_START = _block_start("resource", 2)
_MODULE_START = _block_start("module", 1)
#: `terraform` no lleva etiquetas, asi que se exige que la linea no sea otra cosa (`terraform = x`).
_TERRAFORM_START = re.compile(r"^\s*terraform\s*\{?\s*$")


def _clean_hcl(text: str) -> str:
    """Blanquea comentarios y cuerpos de heredoc conservando lineas y longitud.

    `python-hcl2` no entrega posiciones y el conteo de llaves no debe ver `}` dentro de un
    comentario `/* ... */` ni de un heredoc. Se reemplaza por espacios, no se elimina, para que
    los numeros de linea sigan siendo los del archivo.
    """

    out: list[str] = []
    i, n = 0, len(text)
    en_bloque = False
    heredoc: str | None = None

    while i < n:
        char = text[i]

        if heredoc is not None:
            fin = text.find("\n", i)
            linea = text[i : fin if fin != -1 else n]
            if linea.strip() == heredoc:
                heredoc = None
            out.append(" " * len(linea))
            if fin == -1:
                i = n
            else:
                out.append("\n")
                i = fin + 1
            continue

        if en_bloque:
            if text.startswith("*/", i):
                en_bloque = False
                out.append("  ")
                i += 2
            else:
                out.append("\n" if char == "\n" else " ")
                i += 1
            continue

        if char == '"':
            out.append(char)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue

        if text.startswith("/*", i):
            en_bloque = True
            out.append("  ")
            i += 2
            continue

        if char == "#" or text.startswith("//", i):
            fin = text.find("\n", i)
            if fin == -1:
                out.append(" " * (n - i))
                i = n
            else:
                out.append(" " * (fin - i))
                i = fin
            continue

        if text.startswith("<<", i):
            match = re.match(r"<<-?\s*([A-Za-z_]\w*)", text[i:])
            if match:
                heredoc = match.group(1)
                out.append(" " * len(match.group(0)))
                i += len(match.group(0))
                continue

        out.append(char)
        i += 1

    return "".join(out)


def _brace_delta(line: str) -> int:
    """Llaves abiertas menos cerradas en una linea, sin contar las de strings ni comentarios."""

    delta, in_string, i = 0, False, 0
    while i < len(line):
        char = line[i]
        if in_string:
            if char == "\\":
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "#" or line.startswith("//", i):
            break
        elif char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
        i += 1
    return delta


def _has_open_brace(line: str) -> bool:
    """Si la linea abre un bloque (una llave fuera de strings y comentarios)."""

    in_string, i = False, 0
    while i < len(line):
        char = line[i]
        if in_string:
            if char == "\\":
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "#" or line.startswith("//", i):
            break
        elif char == "{":
            return True
        i += 1
    return False


def block_line_ranges(
    text: str, inicio_bloque: re.Pattern[str]
) -> dict[tuple[str, ...], tuple[int, int]]:
    """(etiquetas) -> (linea inicial, linea final), 1-based, de cada bloque del tipo dado.

    `python-hcl2` no entrega posiciones, asi que se calculan sobre el texto: el bloque empieza en la
    linea `resource "tipo" "nombre" {` y termina donde se cierra su llave (docs/11 OP-15).

    Un bloque sin etiquetas (`terraform {`) se indexa por su orden de aparicion, para que dos en el
    mismo archivo no se pisen."""

    lineas = _clean_hcl(text).splitlines()
    rangos: dict[tuple[str, ...], tuple[int, int]] = {}
    i = 0
    while i < len(lineas):
        inicio = inicio_bloque.match(lineas[i])
        if inicio is None:
            i += 1
            continue

        # La llave puede estar en la misma linea o en la siguiente (HCL lo permite). Se busca la
        # primera linea que abra un bloque, ignorando llaves dentro de strings.
        apertura = next((j for j in range(i, len(lineas)) if _has_open_brace(lineas[j])), None)
        if apertura is None:
            i += 1
            continue

        profundidad, fin = 0, len(lineas) - 1
        for j in range(apertura, len(lineas)):
            profundidad += _brace_delta(lineas[j])
            if profundidad <= 0:
                fin = j
                break
        else:
            fin = len(lineas) - 1  # bloque sin cerrar: hasta el final del archivo
        rangos[inicio.groups() or (str(len(rangos)),)] = (i + 1, fin + 1)
        i = fin + 1
    return rangos


def resource_line_ranges(text: str) -> dict[tuple[str, ...], tuple[int, int]]:
    """Rangos de los bloques `resource`, por (tipo, nombre)."""

    return block_line_ranges(text, _RESOURCE_START)


def _strip_meta(block: dict) -> dict:
    return {k: v for k, v in block.items() if k != "__is_block__"}


class _ArchivoParseado(NamedTuple):
    """Un `.tf` ya leido: su texto original hace falta para los rangos de linea de cada bloque."""

    path: Path
    raw: dict
    text: str
    recursos: list[tuple[str, str, dict]]


#: Prefijos que identifican un `source` de modulo servido por git (docs/02 §3.1).
_FUENTES_GIT = ("git::", "git@", "github.com/", "bitbucket.org/", "gitlab.com/")
#: Prefijos de un archivo descargado por HTTP o de un bucket: externo, pero no git ni registry.
_FUENTES_EXTERNAS = ("http://", "https://", "s3::", "gcs::")
#: `namespace/nombre/proveedor`, con un `//submodulo` opcional: la forma del Terraform Registry.
_FUENTE_REGISTRY = re.compile(r"^[\w.-]+(/[\w.-]+){2}(//[\w./-]+)?$")


def module_origin(source: Any) -> str:
    """De donde viene el codigo de un `module`: `local` es propio, el resto es de terceros.

    La distincion importa porque un modulo local no se puede "fijar" a una version —es codigo del
    mismo repositorio— y penalizarlo por no tenerla seria castigar lo que no es una adquisicion.
    """

    if not isinstance(source, str) or not source.strip() or _is_expression(source):
        return "desconocido"
    valor = source.strip()
    if valor.startswith(("./", "../", "/")):
        return "local"
    if valor.startswith(_FUENTES_GIT) or valor.endswith(".git") or ".git//" in valor:
        return "git"
    if valor.startswith(_FUENTES_EXTERNAS):
        return "externo"
    if _FUENTE_REGISTRY.match(valor):
        return "registry"
    return "desconocido"


def module_pinned(source: Any, version: Any) -> bool:
    """Si la procedencia del modulo esta fijada a algo reproducible.

    `version` es como se fija un modulo del registry; un `source` de git se fija con un
    `?ref=<tag|sha>` en la propia URL, donde el argumento `version` no aplica.
    """

    if isinstance(version, str) and version.strip() and not _is_expression(version):
        return True
    return isinstance(source, str) and "?ref=" in source


#: Se sube a mano cuando cambia lo que el adaptador emite (docs/11 OP-14).
#: v2: emite tf.expression.unresolved y no convierte expresiones en valores (CR-06).
#: v3: emite tf.db_exposure.config (publicly_accessible).
#: v4: el locator trae `line_start`/`line_end` del bloque `resource`, y `tf.resource.present` de un
#: tipo no soportado declara la limitacion (docs/11 OP-15).
#: v5: una regla de security group con CIDR sin resolver se emite con `cidr: unknown` en vez de
#: omitirse.
#: v6: las referencias a un bucket se resuelven entre los `.tf` del directorio, no solo dentro del
#: mismo archivo.
#: v7: `backup_retention_period = 7.0` se lee como 7 dias; la configuracion SSE de S3 usa la
#: primera `rule` que declare `apply_server_side_encryption_by_default`, no siempre `rules[0]`.
#: v8: `dynamic "ingress"/"egress"` se emite como regla con CIDR desconocido (no se ignora).
#: v9: se acepta un `.tf` con BOM UTF-8 (`utf-8-sig`).
#: v10: los rangos de linea ignoran `/* */` y heredocs y aceptan `{` en la linea siguiente.
#: v11: segunda ruta de parseo: los bloques `module` y `terraform { required_providers }`
#: emiten `tf.module.source` y `tf.provider.version` (procedencia del codigo de terceros).
ADAPTER_VERSION = "11"


class TerraformAdapter:
    """Convierte uno o mas archivos `.tf` en instancias de evidencia normalizadas."""

    def __init__(self, source_id: str, scope: str, created_by: str = "adapter:terraform") -> None:
        self.source_id = source_id
        self.scope = scope
        self.created_by = created_by
        self._observed_at = datetime.now(UTC)
        #: Lineas del recurso que se esta procesando; `_make_evidence` las pone en el locator.
        self._lines: tuple[int, int] | None = None

    @staticmethod
    def list_files(path: Path) -> list[Path]:
        """Archivo `.tf` unico, o todos los `.tf` de un directorio."""

        path = Path(path)
        return sorted(path.glob("*.tf")) if path.is_dir() else [path]

    def parse_path(self, path: Path) -> list[EvidenceInstance]:
        """Los `.tf` de un directorio son un solo modulo: una referencia (`aws_s3_bucket.a.id`)
        puede apuntar a un recurso declarado en otro archivo, asi que primero se leen todos."""

        options = SerializationOptions(strip_string_quotes=True)
        archivos: list[_ArchivoParseado] = []
        for file_path in self.list_files(path):
            text = file_path.read_text(encoding="utf-8-sig")
            raw = hcl2.loads(text, serialization_options=options)
            archivos.append(_ArchivoParseado(file_path, raw, text, self._flatten_resources(raw)))
        todos = [recurso for archivo in archivos for recurso in archivo.recursos]

        evidence: list[EvidenceInstance] = []
        for archivo in archivos:
            evidence.extend(
                self._parse_file(
                    archivo.path,
                    archivo.recursos,
                    resource_line_ranges(archivo.text),
                    todos,
                )
            )
            evidence.extend(self._parse_provenance(archivo.path, archivo.raw, archivo.text))
        return evidence

    # -- parsing -----------------------------------------------------------------

    def _parse_file(
        self,
        file_path: Path,
        resources: list[tuple[str, str, dict]],
        rangos: dict[tuple[str, ...], tuple[int, int]],
        all_resources: list[tuple[str, str, dict]],
    ) -> list[EvidenceInstance]:
        evidence: list[EvidenceInstance] = []

        for resource_type, local_name, attrs in resources:
            self._lines = rangos.get((resource_type, local_name))
            evidence.append(self._resource_present_evidence(file_path, resource_type, local_name))
            if resource_type not in _HANDLED_TYPES:
                continue
            evidence.extend(
                self._evidence_for_resource(
                    file_path, resource_type, local_name, attrs, all_resources
                )
            )
        return evidence

    @staticmethod
    def _flatten_resources(raw: dict) -> list[tuple[str, str, dict]]:
        """`resource` en hcl2 es una lista de bloques `{tipo: {nombre: {...attrs}}}`."""

        flattened: list[tuple[str, str, dict]] = []
        for block in raw.get("resource", []):
            for resource_type, by_name in block.items():
                for local_name, attrs in by_name.items():
                    flattened.append((resource_type, local_name, _strip_meta(attrs)))
        return flattened

    # -- procedencia: `module` y `required_providers` ------------------------------

    def _parse_provenance(self, file_path: Path, raw: dict, text: str) -> list[EvidenceInstance]:
        """Segunda ruta de parseo: de donde viene el codigo que el modulo usa (docs/02 §3.1).

        No reutiliza el bucle de `_parse_file`: ese espera la forma `(tipo, nombre, attrs)` y emite
        `tf.resource.present` para todo lo que ve, y ni un `module` ni un `terraform {}` son un
        recurso desplegado. `self._lines` se fija por bloque igual que alli, y se limpia al salir.
        """

        evidence: list[EvidenceInstance] = []

        rangos_modulo = block_line_ranges(text, _MODULE_START)
        for nombre, attrs in self._flatten_modules(raw):
            self._lines = rangos_modulo.get((nombre,))
            evidence.append(self._module_source_evidence(file_path, nombre, attrs))

        # Todas las restricciones viven en el bloque `terraform`, asi que comparten su locator.
        self._lines = block_line_ranges(text, _TERRAFORM_START).get(("0",))
        for proveedor, restriccion in self._required_providers(raw):
            evidence.append(self._provider_version_evidence(file_path, proveedor, restriccion))

        self._lines = None
        return evidence

    @staticmethod
    def _flatten_modules(raw: dict) -> list[tuple[str, dict]]:
        """`module` en hcl2 es una lista de bloques `{nombre: {...attrs}}`."""

        return [
            (nombre, _strip_meta(attrs))
            for block in raw.get("module", [])
            for nombre, attrs in block.items()
        ]

    @staticmethod
    def _required_providers(raw: dict) -> list[tuple[str, str | None]]:
        """(proveedor, restriccion de version) de cada `terraform { required_providers }`.

        Un proveedor declarado sin `version` entra con `None`: declararlo sin fijarlo no es lo mismo
        que no declararlo, y la regla distingue los dos casos.
        """

        encontrados: list[tuple[str, str | None]] = []
        for bloque in raw.get("terraform", []):
            if not isinstance(bloque, dict):
                continue
            grupos = bloque.get("required_providers") or []
            if isinstance(grupos, dict):  # hcl2 envuelve el bloque en una lista, pero no siempre
                grupos = [grupos]
            for grupo in grupos:
                if not isinstance(grupo, dict):
                    continue
                for proveedor, spec in _strip_meta(grupo).items():
                    version = spec.get("version") if isinstance(spec, dict) else None
                    if not isinstance(version, str) or _is_expression(version):
                        version = None
                    encontrados.append((proveedor, (version or "").strip() or None))
        return encontrados

    def _module_source_evidence(
        self, file_path: Path, nombre: str, attrs: dict
    ) -> EvidenceInstance:
        source = attrs.get("source")
        version = attrs.get("version")
        origen = module_origin(source)
        fijada = module_pinned(source, version)
        if origen == "desconocido":
            estado = "unknown"  # el `source` no es literal: no hay procedencia que afirmar
        elif origen == "local":
            estado = "propio"  # codigo del mismo repositorio: no se adquiere, no se fija
        else:
            estado = "fijado" if fijada else "sin_fijar"
        return self._make_evidence(
            type_id="tf.module.source",
            subject_type="module",
            subject_ref=f"module.{nombre}",
            value={
                "nombre": nombre,
                "source": source
                if isinstance(source, str) and not _is_expression(source)
                else None,
                "version": version
                if isinstance(version, str) and not _is_expression(version)
                else None,
                "origen": origen,
                "fijada": fijada,
                "estado": estado,
            },
            file_path=file_path,
            limitations=(
                None
                if origen != "desconocido"
                else "source no literal: procedencia no determinable"
            ),
        )

    def _provider_version_evidence(
        self, file_path: Path, proveedor: str, restriccion: str | None
    ) -> EvidenceInstance:
        return self._make_evidence(
            type_id="tf.provider.version",
            subject_type="provider",
            subject_ref=f"provider.{proveedor}",
            value={
                "proveedor": proveedor,
                "restriccion": restriccion,
                "fijada": restriccion is not None,
                "estado": "fijado" if restriccion is not None else "sin_fijar",
            },
            file_path=file_path,
            limitations=None if restriccion is not None else "declarado sin restriccion de version",
        )

    # -- evidencia por recurso -----------------------------------------------------

    def _resource_present_evidence(
        self, file_path: Path, resource_type: str, local_name: str
    ) -> EvidenceInstance:
        return self._make_evidence(
            type_id="tf.resource.present",
            subject_type=resource_type,
            subject_ref=f"{resource_type}.{local_name}",
            value={"tipo": resource_type, "nombre": local_name, "entorno": None},
            file_path=file_path,
            limitations=(
                None
                if resource_type in _HANDLED_TYPES
                else "tipo de recurso no soportado: se registra su presencia, no sus atributos"
            ),
        )

    def _evidence_for_resource(
        self,
        file_path: Path,
        resource_type: str,
        local_name: str,
        attrs: dict,
        all_resources: list[tuple[str, str, dict]],
    ) -> list[EvidenceInstance]:
        subject_ref = f"{resource_type}.{local_name}"

        if resource_type == "aws_db_instance":
            return [
                *self._rds_encryption(file_path, subject_ref, attrs),
                *self._rds_backup(file_path, subject_ref, attrs),
                self._rds_exposure(file_path, subject_ref, attrs),
                *self._unresolved_for(file_path, resource_type, subject_ref, attrs),
            ]

        if resource_type == "aws_security_group":
            return [
                self._security_group_rules(file_path, subject_ref, attrs),
                *self._unresolved_for(file_path, resource_type, subject_ref, attrs),
            ]

        if resource_type == "aws_cloudtrail":
            return [
                self._cloudtrail_logging(file_path, subject_ref, attrs),
                *self._unresolved_for(file_path, resource_type, subject_ref, attrs),
            ]

        if resource_type in (
            "aws_s3_bucket_server_side_encryption_configuration",
            "aws_s3_bucket_public_access_block",
            "aws_s3_bucket_versioning",
        ):
            target = self._resolve_bucket_ref(attrs.get("bucket"), all_resources)
            if target is None:
                bucket = attrs.get("bucket")
                return [
                    self._unresolved(
                        file_path,
                        resource_type,
                        subject_ref,
                        "bucket",
                        str(bucket),
                        "el bucket al que apunta no se pudo resolver a un aws_s3_bucket local",
                    )
                ]
            unresolved = self._unresolved_for(file_path, resource_type, target, attrs)
            if resource_type == "aws_s3_bucket_server_side_encryption_configuration":
                return [self._s3_encryption(file_path, target, attrs), *unresolved]
            if resource_type == "aws_s3_bucket_public_access_block":
                return [self._s3_public_access(file_path, target, attrs), *unresolved]
            return [self._s3_versioning(file_path, target, attrs), *unresolved]

        return []

    def _unresolved(
        self,
        file_path: Path,
        resource_type: str,
        subject_ref: str,
        atributo: str,
        expresion: str,
        motivo: str = _EXPRESSION_REASON,
    ) -> EvidenceInstance:
        return self._make_evidence(
            type_id="tf.expression.unresolved",
            subject_type=resource_type,
            subject_ref=subject_ref,
            value={
                "recurso": subject_ref,
                "atributo": atributo,
                "expresion": expresion,
                "motivo": motivo,
            },
            file_path=file_path,
            limitations=f"expresion_no_resuelta: {atributo}",
        )

    def _unresolved_for(
        self, file_path: Path, resource_type: str, subject_ref: str, attrs: dict
    ) -> list[EvidenceInstance]:
        watched = _WATCHED_ATTRS.get(resource_type, set())
        return [
            self._unresolved(file_path, resource_type, subject_ref, atributo, expresion)
            for atributo, expresion in _find_unresolved(attrs, watched)
        ]

    @staticmethod
    def _resolve_bucket_ref(
        bucket_value: Any, all_resources: list[tuple[str, str, dict]]
    ) -> str | None:
        ref = _resolve_simple_ref(bucket_value)
        if ref is None:
            return None
        ref_type, ref_name = ref
        for resource_type, local_name, _ in all_resources:
            if resource_type == ref_type and local_name == ref_name:
                return f"{resource_type}.{local_name}"
        return None

    # -- RDS -------------------------------------------------------------------

    def _rds_encryption(
        self, file_path: Path, subject_ref: str, attrs: dict
    ) -> list[EvidenceInstance]:
        storage_encrypted = attrs.get("storage_encrypted")
        if storage_encrypted is True:
            estado = "enabled"
        elif storage_encrypted is False:
            estado = "disabled"
        else:
            estado = "unknown"

        kms_key_id = attrs.get("kms_key_id")
        value = {
            "estado": estado,
            "mecanismo": "aws:kms" if kms_key_id else None,
            "llave": kms_key_id
            if isinstance(kms_key_id, str) and not _is_expression(kms_key_id)
            else None,
        }
        if _is_expression(storage_encrypted):
            limitations: str | None = "expresion_no_resuelta: storage_encrypted"
        elif storage_encrypted is None:
            limitations = "atributo_ausente: storage_encrypted"
        else:
            limitations = None
        return [
            self._make_evidence(
                type_id="tf.encryption.config",
                subject_type="aws_db_instance",
                subject_ref=subject_ref,
                value=value,
                file_path=file_path,
                limitations=limitations,
            )
        ]

    def _rds_exposure(self, file_path: Path, subject_ref: str, attrs: dict) -> EvidenceInstance:
        accesible = attrs.get("publicly_accessible")
        if accesible is True:
            publico: Any = True
        elif accesible is False:
            publico = False
        else:
            publico = "unknown"
        if _is_expression(accesible):
            limitations: str | None = "expresion_no_resuelta: publicly_accessible"
        elif accesible is None:
            limitations = "atributo_ausente: publicly_accessible"
        else:
            limitations = None
        return self._make_evidence(
            type_id="tf.db_exposure.config",
            subject_type="aws_db_instance",
            subject_ref=subject_ref,
            value={"publico": publico},
            file_path=file_path,
            limitations=limitations,
        )

    def _rds_backup(self, file_path: Path, subject_ref: str, attrs: dict) -> list[EvidenceInstance]:
        retencion = attrs.get("backup_retention_period")
        backup_window = attrs.get("backup_window")
        # HCL no distingue `7` de `7.0`: ambos son numeros validos y python-hcl2 puede devolver
        # float. Solo un entero real (o un float integral) es una retencion interpretable.
        dias = (
            int(retencion)
            if isinstance(retencion, int) and not isinstance(retencion, bool)
            else int(retencion)
            if isinstance(retencion, float) and retencion.is_integer()
            else None
        )
        if dias is None:
            value = {"retencion_dias": None, "habilitado": None, "ventana": None}
            limitations = (
                "expresion_no_resuelta: backup_retention_period"
                if _is_expression(retencion)
                else "atributo_ausente: backup_retention_period"
            )
        else:
            value = {
                "retencion_dias": dias,
                "habilitado": dias > 0,
                "ventana": backup_window if not _is_expression(backup_window) else None,
            }
            limitations = None
        return [
            self._make_evidence(
                type_id="tf.backup.config",
                subject_type="aws_db_instance",
                subject_ref=subject_ref,
                value=value,
                file_path=file_path,
                limitations=limitations,
            )
        ]

    # -- S3 ----------------------------------------------------------------------

    def _s3_encryption(self, file_path: Path, subject_ref: str, attrs: dict) -> EvidenceInstance:
        rules = attrs.get("rule") or []
        # S3 admite varias `rule` (p. ej. una por prefijo). Se usa la primera que declare una
        # configuracion por defecto; quedarse con `rules[0]` ignoraba una regla KMS posterior.
        default_rule: dict = {}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            candidato = (rule.get("apply_server_side_encryption_by_default") or [{}])[0]
            if isinstance(candidato, dict) and candidato.get("sse_algorithm") is not None:
                default_rule = candidato
                break
        sse_algorithm = default_rule.get("sse_algorithm")
        if _is_expression(sse_algorithm):
            sse_algorithm = None
        estado = "enabled" if sse_algorithm else "unknown"
        value = {
            "estado": estado,
            "mecanismo": sse_algorithm,
            "llave": kms_key
            if isinstance(kms_key := default_rule.get("kms_master_key_id"), str)
            and not _is_expression(kms_key)
            else None,
        }
        limitations = (
            None if sse_algorithm else "sin bloque apply_server_side_encryption_by_default"
        )
        return self._make_evidence(
            type_id="tf.encryption.config",
            subject_type="aws_s3_bucket",
            subject_ref=subject_ref,
            value=value,
            file_path=file_path,
            limitations=limitations,
        )

    def _s3_public_access(self, file_path: Path, subject_ref: str, attrs: dict) -> EvidenceInstance:
        flags = [
            None if _is_expression(flag) else flag
            for flag in (
                attrs.get("block_public_acls"),
                attrs.get("block_public_policy"),
                attrs.get("ignore_public_acls"),
                attrs.get("restrict_public_buckets"),
            )
        ]
        if any(flag is False for flag in flags):
            bloqueo_publico: Any = False
            nivel = "ninguno"
        elif all(flag is True for flag in flags):
            bloqueo_publico = True
            nivel = "completo"
        elif any(flag is True for flag in flags):
            bloqueo_publico = False
            nivel = "parcial"
        else:
            bloqueo_publico = "unknown"
            nivel = None
        limitations = (
            None if all(f is not None for f in flags) else "atributo_ausente: public_access_block"
        )
        return self._make_evidence(
            type_id="tf.public_access.config",
            subject_type="aws_s3_bucket",
            subject_ref=subject_ref,
            value={"bloqueo_publico": bloqueo_publico, "nivel": nivel},
            file_path=file_path,
            limitations=limitations,
        )

    def _s3_versioning(self, file_path: Path, subject_ref: str, attrs: dict) -> EvidenceInstance:
        config = (attrs.get("versioning_configuration") or [{}])[0]
        status = config.get("status")
        if _is_expression(status):
            status = None
        if status == "Enabled":
            habilitado: Any = True
        elif status == "Suspended":
            habilitado = False
        else:
            habilitado = "unknown"
        return self._make_evidence(
            type_id="tf.versioning.config",
            subject_type="aws_s3_bucket",
            subject_ref=subject_ref,
            value={"habilitado": habilitado},
            file_path=file_path,
            limitations=None if status else "atributo_ausente: versioning_configuration.status",
        )

    # -- Security group ------------------------------------------------------------

    def _security_group_rules(
        self, file_path: Path, subject_ref: str, attrs: dict
    ) -> EvidenceInstance:
        rules: list[dict] = []
        for direccion in ("ingress", "egress"):
            for block in attrs.get(direccion) or []:
                cidrs = [
                    cidr
                    for key in ("cidr_blocks", "ipv6_cidr_blocks")
                    for cidr in _cidrs(block.get(key))
                ]
                for cidr in cidrs:
                    rules.append(
                        {
                            "direccion": direccion,
                            "protocolo": str(block.get("protocol")),
                            "puerto_desde": block.get("from_port"),
                            "puerto_hasta": block.get("to_port"),
                            "cidr": cidr,
                        }
                    )

        # `dynamic "ingress"` no vive en `attrs["ingress"]`: python-hcl2 lo deja en `dynamic`.
        # No se expande `for_each` (puede ser una variable), pero tampoco se ignora: una regla
        # dinámica con origen desconocido impide afirmar que no hay exposición (docs/02 §4).
        for bloque in attrs.get("dynamic") or []:
            if not isinstance(bloque, dict):
                continue
            for direccion in ("ingress", "egress"):
                definicion = bloque.get(direccion) or bloque.get(f'"{direccion}"')
                if not isinstance(definicion, dict):
                    continue
                contenido = (definicion.get("content") or [{}])[0]
                rules.append(
                    {
                        "direccion": direccion,
                        "protocolo": (
                            str(contenido.get("protocol"))
                            if contenido.get("protocol") is not None
                            else None
                        ),
                        "puerto_desde": contenido.get("from_port"),
                        "puerto_hasta": contenido.get("to_port"),
                        "cidr": CIDR_DESCONOCIDO,
                    }
                )
        return self._make_evidence(
            type_id="tf.security_group.rules",
            subject_type="aws_security_group",
            subject_ref=subject_ref,
            value=rules,
            file_path=file_path,
        )

    # -- CloudTrail ---------------------------------------------------------------

    def _cloudtrail_logging(
        self, file_path: Path, subject_ref: str, attrs: dict
    ) -> EvidenceInstance:
        enable_logging = attrs.get("enable_logging")
        if _is_expression(enable_logging):
            habilitado: Any = "unknown"
        else:
            habilitado = True if enable_logging is None else bool(enable_logging)
        multi_region = attrs.get("is_multi_region_trail")
        if _is_expression(multi_region):
            multi_region = None
        return self._make_evidence(
            type_id="tf.logging.config",
            subject_type="aws_cloudtrail",
            subject_ref=subject_ref,
            value={
                "habilitado": habilitado,
                "multi_region": bool(multi_region) if multi_region is not None else None,
                "destino": attrs.get("s3_bucket_name"),
            },
            file_path=file_path,
            limitations=(
                "expresion_no_resuelta: enable_logging" if habilitado == "unknown" else None
            ),
        )

    # -- helpers --------------------------------------------------------------------

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
