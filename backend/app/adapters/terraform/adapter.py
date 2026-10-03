"""Adaptador de Terraform: HCL -> evidencias `tf.*` (docs/02 §3.1).

Alcance declarado: `aws_db_instance`, `aws_s3_bucket` (+ sus recursos de configuracion separados
`aws_s3_bucket_server_side_encryption_configuration`, `aws_s3_bucket_public_access_block`,
`aws_s3_bucket_versioning`), `aws_security_group`, `aws_cloudtrail`.
Solo parsea; nunca ejecuta Terraform ni resuelve el estado real de la nube (docs/02 §7).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _literal_list(value: Any) -> list[Any]:
    """Elementos literales de una lista; una expresion (o un elemento-expresion) se descarta y
    queda registrada como `tf.expression.unresolved`, nunca como un CIDR inventado."""

    if not isinstance(value, list):
        return []
    return [item for item in value if not _is_expression(item)]


_RESOURCE_START = re.compile(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"\s*\{')


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


def resource_line_ranges(text: str) -> dict[tuple[str, str], tuple[int, int]]:
    """(tipo, nombre) -> (linea inicial, linea final), 1-based, de cada bloque `resource`.

    `python-hcl2` no entrega posiciones, asi que se calculan sobre el texto: el bloque empieza en la
    linea `resource "tipo" "nombre" {` y termina donde se cierra su llave (docs/11 OP-15)."""

    lineas = text.splitlines()
    rangos: dict[tuple[str, str], tuple[int, int]] = {}
    i = 0
    while i < len(lineas):
        inicio = _RESOURCE_START.match(lineas[i])
        if inicio is None:
            i += 1
            continue
        profundidad, fin = 0, i
        for j in range(i, len(lineas)):
            profundidad += _brace_delta(lineas[j])
            if profundidad <= 0:
                fin = j
                break
        else:
            fin = len(lineas) - 1  # bloque sin cerrar: hasta el final del archivo
        rangos[(inicio.group(1), inicio.group(2))] = (i + 1, fin + 1)
        i = fin + 1
    return rangos


def _strip_meta(block: dict) -> dict:
    return {k: v for k, v in block.items() if k != "__is_block__"}


#: Se sube a mano cuando cambia lo que el adaptador emite (docs/11 OP-14).
#: v2: emite tf.expression.unresolved y no convierte expresiones en valores (CR-06).
#: v3: emite tf.db_exposure.config (publicly_accessible).
#: v4: el locator trae `line_start`/`line_end` del bloque `resource`, y `tf.resource.present` de un
#: tipo no soportado declara la limitacion (docs/11 OP-15).
ADAPTER_VERSION = "4"


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
        evidence: list[EvidenceInstance] = []
        for file_path in self.list_files(path):
            evidence.extend(self._parse_file(file_path))
        return evidence

    # -- parsing -----------------------------------------------------------------

    def _parse_file(self, file_path: Path) -> list[EvidenceInstance]:
        options = SerializationOptions(strip_string_quotes=True)
        text = file_path.read_text(encoding="utf-8")
        raw = hcl2.loads(text, serialization_options=options)

        resources = self._flatten_resources(raw)
        rangos = resource_line_ranges(text)
        evidence: list[EvidenceInstance] = []

        for resource_type, local_name, attrs in resources:
            self._lines = rangos.get((resource_type, local_name))
            evidence.append(self._resource_present_evidence(file_path, resource_type, local_name))
            if resource_type not in _HANDLED_TYPES:
                continue
            evidence.extend(
                self._evidence_for_resource(file_path, resource_type, local_name, attrs, resources)
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

    def _rds_backup(
        self, file_path: Path, subject_ref: str, attrs: dict
    ) -> list[EvidenceInstance]:
        retencion = attrs.get("backup_retention_period")
        backup_window = attrs.get("backup_window")
        if not isinstance(retencion, int):
            value = {"retencion_dias": None, "habilitado": None, "ventana": None}
            limitations = (
                "expresion_no_resuelta: backup_retention_period"
                if _is_expression(retencion)
                else "atributo_ausente: backup_retention_period"
            )
        else:
            value = {
                "retencion_dias": retencion,
                "habilitado": retencion > 0,
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
        rule = rules[0] if rules else {}
        default_rule = (rule.get("apply_server_side_encryption_by_default") or [{}])[0]
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
            None
            if all(f is not None for f in flags)
            else "atributo_ausente: public_access_block"
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
                    for cidr in _literal_list(block.get(key))
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
