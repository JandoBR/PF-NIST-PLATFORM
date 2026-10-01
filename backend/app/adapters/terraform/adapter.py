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


def _strip_meta(block: dict) -> dict:
    return {k: v for k, v in block.items() if k != "__is_block__"}


class TerraformAdapter:
    """Convierte uno o mas archivos `.tf` en instancias de evidencia normalizadas."""

    def __init__(self, source_id: str, scope: str, created_by: str = "adapter:terraform") -> None:
        self.source_id = source_id
        self.scope = scope
        self.created_by = created_by
        self._observed_at = datetime.now(UTC)

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
        with file_path.open("r", encoding="utf-8") as fh:
            raw = hcl2.load(fh, serialization_options=options)

        resources = self._flatten_resources(raw)
        evidence: list[EvidenceInstance] = []

        for resource_type, local_name, attrs in resources:
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
            ]

        if resource_type == "aws_security_group":
            return [self._security_group_rules(file_path, subject_ref, attrs)]

        if resource_type == "aws_cloudtrail":
            return [self._cloudtrail_logging(file_path, subject_ref, attrs)]

        if resource_type in (
            "aws_s3_bucket_server_side_encryption_configuration",
            "aws_s3_bucket_public_access_block",
            "aws_s3_bucket_versioning",
        ):
            target = self._resolve_bucket_ref(attrs.get("bucket"), all_resources)
            if target is None:
                return []
            if resource_type == "aws_s3_bucket_server_side_encryption_configuration":
                return [self._s3_encryption(file_path, target, attrs)]
            if resource_type == "aws_s3_bucket_public_access_block":
                return [self._s3_public_access(file_path, target, attrs)]
            return [self._s3_versioning(file_path, target, attrs)]

        return []

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
            "llave": kms_key_id if isinstance(kms_key_id, str) else None,
        }
        limitations = (
            None if storage_encrypted is not None else "atributo_ausente: storage_encrypted"
        )
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

    def _rds_backup(
        self, file_path: Path, subject_ref: str, attrs: dict
    ) -> list[EvidenceInstance]:
        retencion = attrs.get("backup_retention_period")
        if not isinstance(retencion, int):
            value = {"retencion_dias": None, "habilitado": None, "ventana": None}
            limitations = "atributo_ausente: backup_retention_period"
        else:
            value = {
                "retencion_dias": retencion,
                "habilitado": retencion > 0,
                "ventana": attrs.get("backup_window"),
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
        estado = "enabled" if sse_algorithm else "unknown"
        value = {
            "estado": estado,
            "mecanismo": sse_algorithm,
            "llave": default_rule.get("kms_master_key_id"),
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
            attrs.get("block_public_acls"),
            attrs.get("block_public_policy"),
            attrs.get("ignore_public_acls"),
            attrs.get("restrict_public_buckets"),
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
                ipv4 = block.get("cidr_blocks") or []
                ipv6 = block.get("ipv6_cidr_blocks") or []
                cidrs = ipv4 + ipv6
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
        habilitado: Any = True if enable_logging is None else bool(enable_logging)
        multi_region = attrs.get("is_multi_region_trail")
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
            locator=Locator(file=str(file_path)),
            observed_at=self._observed_at,
            modality=Modality.DECLARADA,
            limitations=limitations,
            created_by=self.created_by,
        )
