"""U1 — extraccion documental: chunk de texto -> evidencia `doc.claim` validada (docs/05 §2-§3).

La IA produce evidencia, nunca decide el puntaje (docs/05 intro). Este modulo solo valida,
filtra y normaliza; la regla de cada criterio vive en `app/evaluation/rules`.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from app.ai import voting
from app.ai.calllog import call_context
from app.ai.client import AIClient
from app.ai.numbers import normalizar_cantidades
from app.ai.parallel import map_ordered
from app.ai.quotes import quote_in_text
from app.ai.schemas import ExtractionResponse
from app.ai.store import sha256_json, store_bypass, store_for
from app.schemas.evidence import EvidenceInstance, Locator, Modality, Segmento

#: El texto del sistema (`prompts/extract_vN.txt`) no es el prompt completo: `_contenido_esperado`
#: le agrega los campos de `_CONTENT_FIELDS` para los tipos que pide el catalogo. Un cambio ahi
#: cambia el prompt efectivo, asi que **bumpea esta version** -- es lo unico que
#: `core/reproducibility.py` registra de U1, y si no se mueve dos corridas distintas quedan
#: anotadas como la misma.
#: v2: `process_defined.proceso` ofrece `respuesta` (plan de respuesta a incidentes). Sin esa
#: opcion el modelo no podia etiquetar un plan de respuesta y `CRI-RS-01` no lo encontraba
#: (docs/09 §59).
#: v3: `process_defined` suma impactos/probabilidades (ID.RA-04), criterios_recuperacion
#: (RS.MA-05) y planes_actualizados (ID.IM-04); regulariza tambien los tipos y la opcion de enum
#: que la Oleada A habia agregado sin bumpear (docs/09 §76).
#: v4: `supplier_program`, `risk_tolerance` y `role_assigned` suman una faceta por subcategoria de
#: GV.SC, GV.RM y GV.RR, que quedan completas (docs/09 §77).
#: v5: un chunk agrupado puede traer varios tipos (y un inventario de activos junto a uno de datos);
#: se pide extraer cada tipo por separado y reunir en `data_inventory.activos` los recursos
#: tecnologicos de ambas secciones (docs/09 §103).
#: v6: cada afirmacion declara `estado_declarado` (vigente|inexistente|planificado) y se pide
#: normalizar las cantidades escritas con palabras (docs/09 §106).
PROMPT_VERSION = "extract_v6"

#: Limitacion de una afirmacion cuya cita no aparece en el texto analizado (E8).
CITA_NO_LOCALIZABLE = "cita no localizable en el texto analizado: no cuenta para puntuar"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


#: Campos esperados en `contenido` por tipo de afirmacion. Las reglas de cada criterio leen estas
#: claves (docs/03); declararlas aca evita que la IA invente nombres de campo distintos.
_CONTENT_FIELDS: dict[str, str] = {
    "policy_exists": "nombre (string), aprobada_por (string|null)",
    "policy_review": (
        "frecuencia (mensual|trimestral|semestral|anual), ultima_revision (YYYY-MM-DD|null)"
    ),
    "role_assigned": (
        "roles: lista de {rol, responsable, responsabilidades, autoridad},"
        " recursos_asignados (bool|null: se asignan presupuesto, personal o herramientas acordes a"
        " la estrategia de riesgo),"
        " practicas_rh (bool|null: la ciberseguridad esta en las practicas de recursos humanos:"
        " contratacion, induccion, cambios de rol o salida del personal)"
    ),
    "risk_tolerance": (
        "objetivos_riesgo (string), tolerancia (string|null), responsable (string|null),"
        " integracion_empresarial (bool|null: el riesgo de ciberseguridad se gestiona dentro del"
        " riesgo empresarial, no aparte),"
        " opciones_respuesta (bool|null: la estrategia dice que se puede mitigar, transferir,"
        " aceptar o evitar un riesgo),"
        " lineas_comunicacion (bool|null: hay canales definidos para comunicar el riesgo en la"
        " organizacion),"
        " metodo_estandarizado (bool|null: hay un metodo unico para calcular, documentar,"
        " categorizar y priorizar riesgos),"
        " oportunidades_estrategicas (bool|null: las oportunidades, y no solo las amenazas, entran"
        " en la discusion del riesgo)"
    ),
    "data_inventory": (
        "activos (lista de recursos tecnologicos: tipos de recurso como aws_db_instance o"
        " aws_s3_bucket, servidores, bases de datos, buckets, balanceadores, roles y politicas;"
        " reune los del inventario de activos y los que menciona el de datos),"
        " tipos_datos (lista de categorias de datos), clasificacion (string|null),"
        " criticidad (lista de {activo, nivel}|null)"
    ),
    "process_defined": (
        "proceso (riesgos|respuesta|recuperacion|revision|analisis incidentes|contencion"
        "|mejora|otro),"
        " pasos (string),"
        " responsables (string|null), criterios_activacion (string|null),"
        " criterios_declaracion (bool|null), registro_riesgos (bool|null),"
        " priorizacion (bool|null), metricas (bool|null), ajustes (bool|null),"
        " impactos (bool|null: se registran los impactos potenciales de cada riesgo),"
        " probabilidades (bool|null: se registra la probabilidad de cada riesgo),"
        " criterios_recuperacion (bool|null: el documento dice cuando se da por terminada la"
        " respuesta y se inicia la recuperacion),"
        " planes_actualizados (bool|null: los planes de respuesta y otros planes se mantienen y"
        " actualizan con lo aprendido)"
    ),
    "backup_policy": (
        "respaldo (bool), verificacion_integridad (bool|null), retencion (string|null)"
    ),
    "notification_list": ("destinatarios (lista), criterios (string|null), plazos (string|null)"),
    "escalation_path": "niveles (string), criterios (string|null)",
    "org_context": (
        "mision (string|null), partes_interesadas (lista|null), requisitos_legales (lista|null:"
        " legales, regulatorios o contractuales, incluida privacidad), servicios_criticos"
        " (lista|null), dependencias (lista|null: proveedores o servicios externos de los que"
        " depende la operacion)"
    ),
    "supplier_program": (
        "programa (bool: existe un programa o politica de proveedores/terceros), roles (bool|null:"
        " roles y responsabilidades acordados con proveedores), proveedores_priorizados (bool|null:"
        " inventario de proveedores priorizado por criticidad), requisitos_contractuales"
        " (bool|null: requisitos de ciberseguridad en los contratos),"
        " integracion_riesgo (bool|null: el riesgo de proveedores se integra al riesgo de"
        " ciberseguridad y al riesgo empresarial),"
        " debida_diligencia (bool|null: se evalua al proveedor ANTES de formalizar la relacion),"
        " riesgos_monitoreados (bool|null: los riesgos de cada proveedor se registran, priorizan y"
        " se responden durante la relacion),"
        " en_respuesta_incidentes (bool|null: los proveedores participan en la planificacion,"
        " respuesta y recuperacion de incidentes),"
        " monitoreo_ciclo_vida (bool|null: las practicas de seguridad del proveedor se monitorean"
        " a lo largo de la relacion),"
        " terminacion (bool|null: hay disposiciones para el cierre de la relacion, p. ej."
        " devolucion o borrado de datos y revocacion de accesos)"
    ),
    "training_program": (
        "programa (bool: existe un programa de concienciacion o formacion),"
        " frecuencia (mensual|trimestral|semestral|anual), roles_especializados (bool|null:"
        " formacion especifica para roles con acceso privilegiado o funciones de seguridad)"
    ),
    "exposure_policy": (
        "bases_publicas_permitidas (bool|null: false si la politica prohibe bases de datos"
        " accesibles desde Internet, true si las permite), descripcion (string|null)"
    ),
}


#: Campos que las reglas leen como booleanos. Las reglas preguntan por verdad simple
#: (`contenido.get("programa")`), y en Python un `"false"` **string** es verdadero: un modelo que
#: responde texto donde se pide un bool produciria un falso positivo silencioso, justo en los
#: campos que deciden puntaje. Se normalizan aqui, una sola vez, antes de que ninguna regla mire.
_BOOL_FIELDS: dict[str, frozenset[str]] = {
    "process_defined": frozenset(
        {
            "criterios_declaracion",
            "registro_riesgos",
            "priorizacion",
            "metricas",
            "ajustes",
            "impactos",
            "probabilidades",
            "criterios_recuperacion",
            "planes_actualizados",
        }
    ),
    "backup_policy": frozenset({"respaldo", "verificacion_integridad"}),
    "supplier_program": frozenset(
        {
            "programa",
            "roles",
            "proveedores_priorizados",
            "requisitos_contractuales",
            "integracion_riesgo",
            "debida_diligencia",
            "riesgos_monitoreados",
            "en_respuesta_incidentes",
            "monitoreo_ciclo_vida",
            "terminacion",
        }
    ),
    "risk_tolerance": frozenset(
        {
            "integracion_empresarial",
            "opciones_respuesta",
            "lineas_comunicacion",
            "metodo_estandarizado",
            "oportunidades_estrategicas",
        }
    ),
    "role_assigned": frozenset({"recursos_asignados", "practicas_rh"}),
    "training_program": frozenset({"programa", "roles_especializados"}),
    "exposure_policy": frozenset({"bases_publicas_permitidas"}),
}

#: Lo que se acepta como bool escrito en texto. Cualquier otra cosa se descarta: inventar una
#: interpretacion seria peor que tratar el campo como ausente.
_BOOL_TEXTO = {
    "true": True,
    "false": False,
    "si": True,
    "sí": True,
    "no": False,
    "yes": True,
    "1": True,
    "0": False,
}

#: Frecuencias de revision aceptadas (docs/05 §2.3 E5); otro valor se descarta.
_FRECUENCIAS = {"mensual", "trimestral", "semestral", "anual"}
_FECHA_MINIMA = date(1990, 1, 1)
_ROL_MAX_CHARS = 120

#: Estados que el documento puede declarar sobre la practica (prompt v6, docs/09 §106). Una
#: afirmacion sin estado es de antes de v6 y se lee como vigente; un estado que no se entiende no
#: se interpreta y la afirmacion se descarta (no se convierte un error de formato en una ausencia).
_ESTADOS_DECLARADOS = ("vigente", "inexistente", "planificado")

#: Campos de `contenido` que expresan una cantidad o un plazo y por eso se normalizan a digitos.
_CAMPOS_CANTIDAD: dict[str, tuple[str, ...]] = {
    "backup_policy": ("retencion",),
    "risk_tolerance": ("tolerancia",),
    "notification_list": ("plazos",),
    "process_defined": ("criterios_activacion",),
}


def _estado_declarado(valor: object) -> str | None:
    """Estado declarado normalizado, o `None` si el modelo respondio algo que no se entiende."""

    if valor is None:
        return "vigente"
    normalizado = str(valor).strip().lower()
    return normalizado if normalizado in _ESTADOS_DECLARADOS else None


def _frecuencia(texto: str) -> str | None:
    """Frecuencia reconocida a partir del texto, incluida una cantidad escrita con palabras
    ("cada tres meses" -> "trimestral")."""

    normalizado = normalizar_cantidades(str(texto)).strip().lower()
    if normalizado in _FRECUENCIAS:
        return normalizado
    if re.search(r"\b12\s*(mes|meses)\b|\b1\s*a(?:ñ|n)os?\b", normalizado):
        return "anual"
    if re.search(r"\b6\s*(mes|meses)\b", normalizado):
        return "semestral"
    if re.search(r"\b3\s*(mes|meses)\b", normalizado):
        return "trimestral"
    if re.search(r"\b1\s*mes\b", normalizado):
        return "mensual"
    return None


def _sanitize_content(tipo: str, contenido: dict) -> dict:
    """E5 (docs/05 §2.3): campos de fecha/rol se validan contra formatos esperados y los valores
    absurdos se descartan. El campo descartado se quita (los criterios lo ven como ausente) y queda
    anotado en `_descartados`; la afirmacion no se invalida entera."""

    limpio = dict(contenido)
    descartados: list[str] = []

    if tipo == "policy_review":
        ultima = limpio.get("ultima_revision")
        if ultima is not None:
            try:
                fecha = date.fromisoformat(str(ultima))
                valida = _FECHA_MINIMA <= fecha <= date.today() + timedelta(days=1)
            except ValueError:
                valida = False
            if not valida:
                limpio["ultima_revision"] = None
                descartados.append(f"ultima_revision={ultima!r}: fecha invalida o fuera de rango")
        frecuencia = limpio.get("frecuencia")
        if frecuencia is not None:
            reconocida = _frecuencia(frecuencia)
            if reconocida is None:
                limpio["frecuencia"] = None
                descartados.append(f"frecuencia={frecuencia!r}: no es una frecuencia reconocida")
            elif str(frecuencia).strip().lower() not in _FRECUENCIAS:
                limpio["frecuencia"] = reconocida

    for campo in _CAMPOS_CANTIDAD.get(tipo, ()):
        valor = limpio.get(campo)
        if isinstance(valor, str) and valor.strip():
            limpio[campo] = normalizar_cantidades(valor)

    if tipo == "role_assigned" and "roles" in limpio:
        roles = limpio["roles"]
        if not isinstance(roles, list):
            limpio.pop("roles")
            descartados.append("roles: se esperaba una lista")
        else:
            validos = [
                r
                for r in roles
                if isinstance(r, dict)
                and isinstance(r.get("rol"), str)
                and 0 < len(r["rol"].strip()) <= _ROL_MAX_CHARS
            ]
            if len(validos) != len(roles):
                descartados.append(f"roles: {len(roles) - len(validos)} entrada(s) invalida(s)")
            limpio["roles"] = validos

    for campo in _BOOL_FIELDS.get(tipo, ()):
        if campo not in limpio:
            continue
        valor = limpio[campo]
        if valor is None or isinstance(valor, bool):
            continue
        normalizado = _BOOL_TEXTO.get(str(valor).strip().lower())
        if normalizado is None:
            limpio.pop(campo)
            descartados.append(f"{campo}={valor!r}: no es un booleano interpretable")
        else:
            limpio[campo] = normalizado

    if descartados:
        limpio["_descartados"] = descartados
    return limpio


def _contenido_esperado(tipos: list[str]) -> str:
    return "\n".join(
        f"- {tipo}: {_CONTENT_FIELDS.get(tipo, 'campos que describan la afirmacion')}"
        for tipo in tipos
    )


def _build_user_prompt(chunk_text: str, tipos_solicitados: list[str], doc_id: str) -> str:
    tipos = ", ".join(tipos_solicitados)
    return (
        f'<documento id="{doc_id}">\n{chunk_text}\n</documento>\n\n'
        f"Tipos de afirmacion a buscar en este fragmento: {tipos}.\n"
        f"Para 'contenido', usa estos campos por tipo:\n{_contenido_esperado(tipos_solicitados)}\n"
        "En cada afirmacion indica 'estado_declarado': vigente, inexistente o planificado.\n"
        "Responde en JSON con el esquema indicado."
    )


def _locator_de_cita(
    fragmento: str,
    chunk_text: str,
    chunk_locator: Locator,
    segmentos: tuple[Segmento, ...],
) -> Locator:
    """Locator de la seccion/pagina que contiene la cita (docs/05 §2.1).

    El chunk agrupa varias secciones; la posicion de la cita dentro del texto agrupado decide cual
    se cita, no la primera. Si no se localiza en ningun tramo -- no deberia: E8 ya la valido --
    vale el locator del primer tramo, que es el del chunk."""

    for segmento in segmentos:
        if quote_in_text(fragmento, chunk_text[segmento.inicio : segmento.fin]):
            return segmento.locator
    return chunk_locator


def _u1_input_sha256(chunk_text: str, tipos_solicitados: list[str], doc_id: str) -> str:
    """Insumo canonico de U1: sin ids de evidencia, tipos ordenados (docs/05 §7)."""

    return sha256_json(
        {"chunk_text": chunk_text, "doc_id": doc_id, "tipos": sorted(tipos_solicitados)}
    )


def _claims_from_raw(
    raw: dict | None,
    *,
    chunk_text: str,
    chunk_locator: Locator,
    tipos_solicitados: list[str],
    doc_id: str,
    source_id: str,
    scope: str,
    confianza_minima: float,
    segmentos: tuple[Segmento, ...] = (),
) -> list[EvidenceInstance]:
    """Valida y convierte una respuesta cruda de U1 en evidencia (E1-E8, docs/05 §2.3)."""

    if raw is None:
        return []  # degradado: sin respuesta util, no se inventa evidencia (E4/J4)

    try:
        parsed = ExtractionResponse.model_validate(raw)
    except ValidationError:
        return []  # JSON invalido contra el esquema: se descarta, nunca crashea (R5)

    observed_at = datetime.now(UTC)
    evidence: list[EvidenceInstance] = []

    for claim in parsed.afirmaciones:
        if claim.tipo not in tipos_solicitados:
            continue  # la IA no introduce tipos de afirmacion fuera de lo pedido (D5)

        if claim.encontrado and (claim.cita is None or not claim.cita.fragmento.strip()):
            continue  # E2: una afirmacion encontrada sin cita.fragmento se descarta

        limitaciones: list[str] = []
        estado: str | None = None
        if claim.encontrado:
            estado = _estado_declarado(claim.estado_declarado)
            if estado is None:
                continue  # E5: un estado de la practica que no se entiende no se interpreta
        if claim.encontrado and claim.confianza < confianza_minima:
            limitaciones.append(f"confianza baja ({claim.confianza} < {confianza_minima})")  # E3
        if claim.encontrado and not quote_in_text(claim.cita.fragmento, chunk_text):
            # E8: la cita tiene que estar en el texto enviado. Una cita que no aparece no se puede
            # verificar: la afirmacion se guarda (queda a la vista) pero no cuenta para puntuar,
            # igual que una de confianza baja.
            limitaciones.append(CITA_NO_LOCALIZABLE)
        limitations = "; ".join(limitaciones) or None

        locator = chunk_locator
        if claim.cita is not None:
            if segmentos:
                locator = _locator_de_cita(
                    claim.cita.fragmento, chunk_text, chunk_locator, segmentos
                )
            else:
                locator = Locator(
                    file=chunk_locator.file,
                    page=claim.cita.pagina if claim.cita.pagina is not None else chunk_locator.page,
                    section=(
                        claim.cita.seccion
                        if claim.cita.seccion is not None
                        else chunk_locator.section
                    ),
                )

        evidence.append(
            EvidenceInstance(
                type_id="doc.claim",
                type_version=3,
                subject_type="document",
                subject_ref=f"doc:{doc_id}",
                scope=scope,
                value={
                    "tipo_afirmacion": claim.tipo,
                    "contenido": _sanitize_content(claim.tipo, claim.contenido),
                    "encontrado": claim.encontrado,
                    "confianza": claim.confianza,
                    # v2: la cita textual, para poder mostrarla y auditarla despues.
                    "cita": claim.cita.fragmento if claim.cita is not None else None,
                    # v3: si el documento afirma la practica como vigente, la niega o la declara
                    # planificada (docs/09 §106). Ausente solo en afirmaciones no encontradas.
                    "estado_declarado": estado,
                },
                source_id=source_id,
                locator=locator,
                observed_at=observed_at,
                modality=Modality.DOCUMENTAL,
                limitations=limitations,
                created_by="ai:extraction",
            )
        )

    return evidence


def _run_once(
    client: AIClient,
    *,
    user_prompt: str,
    input_sha256: str,
    voto: int,
    bypass: bool,
    **parse: object,
) -> tuple[dict | None, list[EvidenceInstance]]:
    """Una corrida cruda de U1. En una votacion, `bypass` evita que la segunda corrida sea un
    "hit": votar sobre tres veces el mismo resultado guardado no dice nada (docs/05 §7)."""

    with call_context(
        paso="U1",
        prompt_version=PROMPT_VERSION,
        doc_id=parse["doc_id"],
        input_sha256=input_sha256,
        voto=voto,
    ):
        if bypass:
            with store_bypass():
                raw = client.complete_json(_SYSTEM_PROMPT, user_prompt)
        else:
            # Sin votacion el resultado si se puede reutilizar: lo cachea el propio cliente
            # (store en BD en api/workers, disco en la CLI) por el mismo insumo canonico.
            raw = client.complete_json(_SYSTEM_PROMPT, user_prompt)
    return raw, _claims_from_raw(raw, **parse)


def extract_claims(
    client: AIClient,
    *,
    chunk_text: str,
    chunk_locator: Locator,
    tipos_solicitados: list[str],
    doc_id: str,
    source_id: str,
    scope: str,
    confianza_minima: float,
    segmentos: tuple[Segmento, ...] = (),
) -> list[EvidenceInstance]:
    """Ejecuta U1 sobre un chunk y devuelve evidencia `doc.claim` (reglas E1-E7, docs/05 §2.3).

    `segmentos` son las secciones/paginas que el chunk agrupa: con ellas el locator de cada
    afirmacion apunta a la seccion/pagina de su cita y no a la primera del chunk.

    Con store persistente, el resultado se lee y se guarda por insumo canonico; en un miss corre
    `U1_VOTES` corridas (3 por defecto) y guarda la afirmacion votada. Las corridas se validan
    por separado antes de votar, para que una cita inventada o de baja confianza no arrastre el
    voto (docs/05 §2.4)."""

    user_prompt = _build_user_prompt(chunk_text, tipos_solicitados, doc_id)
    input_sha256 = _u1_input_sha256(chunk_text, tipos_solicitados, doc_id)
    n = voting.votes()
    store = store_for(client)

    if store is not None and n > 1:
        guardado = store.get("U1", PROMPT_VERSION, input_sha256)
        if guardado is not None:
            return _claims_from_raw(
                guardado,
                chunk_text=chunk_text,
                chunk_locator=chunk_locator,
                tipos_solicitados=tipos_solicitados,
                doc_id=doc_id,
                source_id=source_id,
                scope=scope,
                confianza_minima=confianza_minima,
                segmentos=segmentos,
            )

    parse = {
        "chunk_text": chunk_text,
        "chunk_locator": chunk_locator,
        "tipos_solicitados": tipos_solicitados,
        "doc_id": doc_id,
        "source_id": source_id,
        "scope": scope,
        "confianza_minima": confianza_minima,
        "segmentos": segmentos,
    }
    if n <= 1:
        raw, claims = _run_once(
            client,
            user_prompt=user_prompt,
            input_sha256=input_sha256,
            voto=1,
            bypass=False,
            **parse,
        )
        runs = [(raw, claims)]
    else:
        runs = map_ordered(
            lambda indice: _run_once(
                client,
                user_prompt=user_prompt,
                input_sha256=input_sha256,
                voto=indice + 1,
                bypass=True,
                **parse,
            ),
            range(n),
        )
        claims = voting.vote([claims for _, claims in runs])

    if store is not None and n > 1:
        if sum(1 for raw, _ in runs if raw is not None) >= voting.umbral(n):
            store.put(
                "U1",
                PROMPT_VERSION,
                input_sha256,
                voting.claims_to_raw(claims),
                voting.run_summary(runs),
            )
    return claims
