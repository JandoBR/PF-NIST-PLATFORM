"""Helpers compartidos por las reglas de criterio."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import PurePath

from app.evaluation.schemas import CriterionResult, Estado
from app.schemas.evidence import EvidenceInstance

#: Valores de un campo que no declaran nada. `False` no esta: un booleano en falso si dice algo.
SIN_DATO = (None, "", [], {})


def by_type(evidence: list[EvidenceInstance], type_id: str) -> list[EvidenceInstance]:
    return [e for e in evidence if e.type_id == type_id]


def doc_claims(evidence: list[EvidenceInstance], tipo_afirmacion: str) -> list[EvidenceInstance]:
    """`doc.claim` de un `tipo_afirmacion`, excluyendo los de confianza baja (E3, docs/05 §2.3):
    una confianza baja no cuenta como evidencia suficiente."""

    return [
        e
        for e in by_type(evidence, "doc.claim")
        if e.value.get("tipo_afirmacion") == tipo_afirmacion and e.limitations is None
    ]


def best_found_with(claims: list[EvidenceInstance], campo: str) -> EvidenceInstance | None:
    """Como `best_found`, pero solo entre las afirmaciones que traen `contenido[campo]` con algo.

    Una afirmacion encontrada que calla ese dato (p. ej. una `notification_list` sin
    `destinatarios`) no compite con otra que si lo declara, aunque tenga mas confianza: no dice
    algo distinto, no dice nada sobre ese campo."""

    return best_found(
        [c for c in claims if (c.value.get("contenido") or {}).get(campo) not in SIN_DATO]
    )


def _orden(claim: EvidenceInstance) -> tuple:
    """Orden estable y determinista de las afirmaciones: confianza, documento, contenido."""

    return (
        -claim.value.get("confianza", 0),
        claim.subject_ref,
        json.dumps(claim.value.get("contenido", {}), sort_keys=True, ensure_ascii=False),
    )


def found(claims: list[EvidenceInstance]) -> list[EvidenceInstance]:
    """Las afirmaciones `encontrado=true` que declaran la practica **vigente**.

    Un plan declarado ("se implementara en 2027") tambien trae `encontrado=true`, pero no acredita
    la practica de hoy: una regla no puede sumarlo como si ya estuviera en marcha (docs/09 §106).
    Sigue disponible para `aplicar_estado_declarado`, que lo convierte en 0 citandolo."""

    return sorted(
        (c for c in claims if c.value.get("encontrado") and not es_plan_declarado(c)),
        key=_orden,
    )


#: Lo que el documento declara sobre la practica (`doc.claim@3`, docs/09 §106).
ESTADO_VIGENTE = "vigente"
ESTADO_INEXISTENTE = "inexistente"
ESTADO_PLANIFICADO = "planificado"
_ESTADOS_DECLARADOS = (ESTADO_VIGENTE, ESTADO_INEXISTENTE, ESTADO_PLANIFICADO)


def estado_declarado(claim: EvidenceInstance) -> str:
    """Estado que la afirmacion declara sobre la practica.

    Una afirmacion guardada antes de `doc.claim@3` no trae el campo: se lee como vigente, que es lo
    que significaba entonces. `extraction` descarta un valor que no reconoce, asi que un valor
    invalido solo puede venir de evidencia manipulada y tampoco se interpreta como ausencia."""

    valor = claim.value.get("estado_declarado")
    return valor if valor in _ESTADOS_DECLARADOS else ESTADO_VIGENTE


def es_ausencia_declarada(claim: EvidenceInstance) -> bool:
    """El documento niega explicitamente la practica ("no hay responsable de seguridad")."""

    return (
        bool(claim.value.get("encontrado"))
        and claim.limitations is None
        and estado_declarado(claim) == ESTADO_INEXISTENTE
    )


def es_plan_declarado(claim: EvidenceInstance) -> bool:
    """El documento declara la practica como futura o pendiente ("se implementara en 2027")."""

    return (
        bool(claim.value.get("encontrado"))
        and claim.limitations is None
        and estado_declarado(claim) == ESTADO_PLANIFICADO
    )


def es_vigente(claim: EvidenceInstance) -> bool:
    """La afirmacion declara la practica vigente hoy: ni ausencia declarada ni plan futuro."""

    return (
        bool(claim.value.get("encontrado"))
        and claim.limitations is None
        and estado_declarado(claim) == ESTADO_VIGENTE
    )


#: Proceso declarado (`process_defined.contenido.proceso`) -> faceta canonica. `process_defined`
#: sirve a criterios distintos segun el proceso, asi que negar "otro" no niega la practica de
#: respuesta ni la de riesgos (docs/09 §108).
_PROCESO_ALIAS: tuple[tuple[str, str], ...] = (
    ("respuesta", "respuesta"),
    ("response", "respuesta"),
    ("escalamiento", "respuesta"),
    ("recuperacion", "recuperacion"),
    ("recovery", "recuperacion"),
    ("riesgo", "riesgos"),
    ("risk", "riesgos"),
    ("analisis", "analisis incidentes"),
    ("contencion", "contencion"),
    ("erradicacion", "contencion"),
    ("mejora", "mejora"),
    ("leccion", "mejora"),
    ("revision", "revision"),
    ("desempeno", "revision"),
    ("incidente", "analisis incidentes"),
)


def proceso_faceta(claim: EvidenceInstance) -> str | None:
    """Faceta del proceso que declara una `process_defined`, o `None` si no identifica ninguna."""

    proceso = str((claim.value.get("contenido") or {}).get("proceso") or "").lower()
    for palabra, faceta in _PROCESO_ALIAS:
        if palabra in proceso:
            return faceta
    return None


#: Faceta de una `policy_exists` que no nombra ninguna politica: la afirmacion habla de "una
#: politica" en general y contradice a cualquiera que se nombre (docs/09 §109).
POLITICA_GENERICA = "*"


def _texto_normalizado(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(sin_tildes.casefold().split())


def politica_faceta(claim: EvidenceInstance) -> str:
    """La politica que nombra una `policy_exists`, normalizada; `POLITICA_GENERICA` si no nombra
    ninguna.

    Dos documentos que niegan y afirman politicas distintas -- la de proveedores y la de seguridad
    de la informacion -- no son la misma practica: sin separarlas, la negacion de una ponia el
    criterio de la otra en `evidencia_insuficiente` (docs/09 §109)."""

    nombre = _texto_normalizado(str((claim.value.get("contenido") or {}).get("nombre") or ""))
    for prefijo in ("politica de ", "politica del ", "politica ", "policy of ", "policy "):
        if nombre.startswith(prefijo):
            nombre = nombre.removeprefix(prefijo)
            break
    return _texto_normalizado(nombre) or POLITICA_GENERICA


def faceta(claim: EvidenceInstance) -> tuple[str, ...]:
    """Que practica declara la afirmacion, para no mezclar facetas de un mismo tipo.

    Un `process_defined` de respuesta y uno de recuperacion son practicas distintas aunque
    compartan el tipo, igual que dos `policy_exists` que nombran politicas distintas; el resto de
    tipos declara una sola faceta (docs/09 §108, §109)."""

    tipo = str(claim.value.get("tipo_afirmacion"))
    if tipo == "process_defined":
        return (tipo, proceso_faceta(claim) or "")
    if tipo == "policy_exists":
        return (tipo, politica_faceta(claim))
    return (tipo,)


def facetas_compatibles(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Las dos afirmaciones describen la misma practica.

    Una `policy_exists` sin nombre habla de cualquier politica, asi que contradice a una nombrada;
    dos politicas con nombres distintos son practicas distintas (docs/09 §109)."""

    if a == b:
        return True
    return a[0] == b[0] == "policy_exists" and POLITICA_GENERICA in (a[1], b[1])


def _declaraciones(claims: list[EvidenceInstance], tipo: str) -> list[EvidenceInstance]:
    return [
        c
        for c in claims
        if c.value.get("tipo_afirmacion") == tipo
        and c.value.get("encontrado")
        and c.limitations is None
    ]


def _cita(claim: EvidenceInstance) -> str:
    cita = str(claim.value.get("cita") or "").strip()
    return f" «{cita}»" if cita else ""


def aplicar_estado_declarado(
    resultado: CriterionResult, evidence: list[EvidenceInstance]
) -> CriterionResult:
    """Convierte una negacion o un plan explicito del documento en el resultado que corresponde.

    Una afirmacion `encontrado=true` describia la practica aunque el texto dijera "no existe": la
    regla la sumaba como si estuviera vigente. Aca, una vez calculada la regla, se mira el estado
    de las afirmaciones que la regla cito (docs/09 §106):

    - `inexistente`: el documento da evidencia explicita de ausencia, asi que el criterio es
      `no_implementado` con 0 y la explicacion cita el documento (`docs/01 §3`). No es silencio
      documental: el documento habla, y dice que la practica no esta.
    - `planificado`: el documento declara que la practica llegara despues. Tampoco se acredita
      (`no_implementado`, 0): un plan es informacion explicita de que hoy no esta en marcha.
      `found` lo excluye de la suma de contenido, asi que un plan nunca aporta campos por si solo.

    Vale si el criterio se apoyo en esa afirmacion y ningun otro documento la declara vigente. Si
    otro documento la afirma, no se elige ganador: la contradiccion documento-vs-documento ya
    excluye ambas afirmaciones para ese criterio (`evaluation/contradictions.py`, docs/02 §5), y
    aca se deja la nota visible por si la exclusion no llego a aplicarse. Una regla que no pudo
    acreditar nada (`evidencia_insuficiente`) tambien pasa a 0: con una negacion o un plan delante,
    el documento no calla, dice que la practica no esta. El motor lo aplica a todas las reglas,
    igual que `marcar_sin_respuesta` y `marcar_contradicciones`.

    Solo cuentan las declaraciones de la **misma faceta** que el criterio cito: `RS-01` lee el
    `process_defined` de respuesta y la negacion de "recuperacion" pertenece a `RC-01`, no a el
    (docs/09 §108). Lo mismo con `policy_exists`: la negacion de la politica de proveedores no
    habla de la politica de seguridad de la informacion (docs/09 §109)."""

    if (
        resultado.estado in (Estado.ERROR, Estado.NO_APLICABLE)
        or not resultado.evidence_ids
        or AVISO_SIN_RESPUESTA in resultado.explanation
    ):
        return resultado

    todas = by_type(evidence, "doc.claim")
    por_id = {c.id: c for c in todas}
    citadas = [por_id[i] for i in resultado.evidence_ids if i in por_id]
    if not citadas:
        return resultado

    for tipo in sorted({str(c.value.get("tipo_afirmacion")) for c in citadas}):
        facetas = {faceta(c) for c in citadas if str(c.value.get("tipo_afirmacion")) == tipo}
        declaraciones = [
            c
            for c in _declaraciones(todas, tipo)
            if any(facetas_compatibles(faceta(c), f) for f in facetas)
        ]
        negadas = [c for c in declaraciones if estado_declarado(c) == ESTADO_INEXISTENTE]
        planes = [c for c in declaraciones if estado_declarado(c) == ESTADO_PLANIFICADO]
        if not negadas and not planes:
            continue
        elegida = sorted(negadas or planes, key=_orden)[0]
        mismo_scope = [c for c in declaraciones if c.scope == elegida.scope]
        vigentes = [c for c in mismo_scope if estado_declarado(c) == ESTADO_VIGENTE]
        if vigentes:
            otro = next(
                (v for v in vigentes if v.subject_ref != elegida.subject_ref),
                None,
            )
            if otro is not None:
                if not negadas:
                    continue  # otro documento declara la practica planificada como vigente
                detalle = ", ".join(
                    _archivo(c)
                    for c in sorted(negadas + planes, key=_orden)
                    if c.scope == elegida.scope
                )
                return resultado.model_copy(
                    update={
                        "explanation": (
                            f"{resultado.explanation} Contradiccion documental: {detalle} declara"
                            f" que no existe y {_archivo(otro)} lo declara vigente; no se elige un"
                            " ganador."
                        )
                    }
                )
            if resultado.estado != Estado.EVIDENCIA_INSUFICIENTE:
                continue  # el mismo documento tambien lo afirma: vale la mas confiable (§101)

        if estado_declarado(elegida) == ESTADO_INEXISTENTE:
            explicacion = (
                f"El documento {_archivo(elegida)} declara que no existe: {_cita(elegida)}."
                " Es evidencia explicita de ausencia, no silencio documental."
            )
        else:
            explicacion = (
                f"El documento {_archivo(elegida)} declara la practica como planificada, no"
                f" vigente: {_cita(elegida)}. Un plan declarado no acredita la practica hoy."
            )
        return result(
            str(resultado.criterion_id),
            Estado.EVALUADO,
            0,
            explicacion,
            [elegida.id],
        )

    return resultado


@dataclass(frozen=True)
class ContradiccionBooleana:
    """Un campo booleano que un mismo documento declara y niega en fragmentos distintos.

    `valor` es el que usa la regla: el de la afirmacion mas confiable del documento, porque un
    `false` puede ser una negacion explicita ("no se realiza X") y sumarlo con `or` inflaria el
    puntaje (docs/09 §101).
    """

    tipo_afirmacion: str
    campo: str
    documento: str
    archivo: str
    valor: bool
    claim_ids: tuple[str, ...]


def _archivo(claim: EvidenceInstance) -> str:
    return PurePath(claim.locator.file).name if claim.locator.file else claim.subject_ref


def _resolver_booleano(
    declarantes: list[EvidenceInstance], tipo: str, campo: str
) -> tuple[bool, list[EvidenceInstance], list[ContradiccionBooleana]]:
    """Valor agregado de un campo booleano, las afirmaciones que lo aportan y sus contradicciones.

    Entre documentos se mantiene el `or`: una practica declarada en un documento de la organizacion
    cuenta aunque otro no la mencione. Dentro de un mismo documento no: si una afirmacion lo
    declara y otra lo niega, vale la de mayor confianza (mismo orden que `found`) y la negacion no
    desaparece, queda como `ContradiccionBooleana`.

    `declarantes` viene en orden de `found`: la primera de cada documento es la mas confiable."""

    por_documento: dict[str, list[EvidenceInstance]] = {}
    for claim in declarantes:
        por_documento.setdefault(claim.subject_ref, []).append(claim)

    usados: list[EvidenceInstance] = []
    conflictos: list[ContradiccionBooleana] = []
    for documento in sorted(por_documento):
        del_documento = por_documento[documento]
        elegido = del_documento[0]
        elegido_valor = bool(elegido.value["contenido"][campo])
        if any(bool(c.value["contenido"][campo]) != elegido_valor for c in del_documento[1:]):
            conflictos.append(
                ContradiccionBooleana(
                    tipo_afirmacion=tipo,
                    campo=campo,
                    documento=documento,
                    archivo=_archivo(elegido),
                    valor=elegido_valor,
                    claim_ids=tuple(c.id for c in del_documento),
                )
            )
        if elegido_valor:
            usados.append(elegido)
    return bool(usados), usados or declarantes[:1], conflictos


def merged_bool(claims: list[EvidenceInstance], campo: str) -> tuple[bool, list[EvidenceInstance]]:
    """Booleano agregado de varias afirmaciones del mismo tipo, con la regla de `merged_content`:
    `or` entre documentos, valor de la mas confiable dentro de uno que se contradice."""

    declarantes = [
        c for c in found(claims) if isinstance((c.value.get("contenido") or {}).get(campo), bool)
    ]
    if not declarantes:
        return False, []
    valor, usados, _ = _resolver_booleano(
        declarantes, str(declarantes[0].value.get("tipo_afirmacion", "")), campo
    )
    return valor, usados


def merged_content(
    claims: list[EvidenceInstance],
) -> tuple[dict, list[EvidenceInstance]]:
    """Contenido de varias afirmaciones del mismo tipo como si fueran una sola.

    Un documento largo se parte en fragmentos y cada fragmento produce su propia afirmacion: GV.OC,
    por ejemplo, reparte sus cinco datos en cuatro `doc.claim`. Puntuar solo la mejor afirmacion
    mediria un fragmento y no el documento, asi que campo a campo se toma el valor de la afirmacion
    mas confiable que **declara** ese campo -- una que lo calla no compite --, salvo los booleanos,
    que se agregan con `or` entre documentos. Dentro de un mismo documento que se contradice (un
    fragmento declara la practica y otro la niega) vale el valor de la afirmacion mas confiable, no
    el `or`: un `false` puede ser una negacion explicita y sumarlo inflaria el puntaje (docs/09
    §101). `contradicciones_booleanas` devuelve esos casos para que el motor los haga visibles.

    Devuelve el contenido agregado y las afirmaciones que aportaron algun campo, para citarlas
    todas. Sin afirmaciones `encontrado=true` el contenido queda vacio.
    """

    encontradas = found(claims)
    contenido: dict = {}
    aportantes: dict[str, EvidenceInstance] = {}
    for campo in sorted({k for c in encontradas for k in (c.value.get("contenido") or {})}):
        declarantes = [
            c for c in encontradas if (c.value.get("contenido") or {}).get(campo) not in SIN_DATO
        ]
        if not declarantes:
            continue
        valores = [c.value["contenido"][campo] for c in declarantes]
        if all(isinstance(v, bool) for v in valores):
            valor, usados, _ = _resolver_booleano(
                declarantes, str(declarantes[0].value.get("tipo_afirmacion", "")), campo
            )
            contenido[campo] = valor
        else:
            contenido[campo] = valores[0]
            usados = declarantes[:1]
        for claim in usados:
            aportantes[claim.id] = claim
    return contenido, sorted(aportantes.values(), key=_orden)


def contradicciones_booleanas(
    evidence: list[EvidenceInstance],
) -> list[ContradiccionBooleana]:
    """Campos booleanos que un mismo documento declara y niega (docs/09 §101).

    Se calcula sobre la misma evidencia que leen las reglas (`doc.claim` con `encontrado=true` y
    sin limitaciones), asi que lo que el motor anota es exactamente lo que `merged_content` uso."""

    conflictos: list[ContradiccionBooleana] = []
    tipos = sorted(
        {
            str(c.value.get("tipo_afirmacion"))
            for c in by_type(evidence, "doc.claim")
            if c.value.get("tipo_afirmacion")
        }
    )
    for tipo in tipos:
        encontradas = found(doc_claims(evidence, tipo))
        campos = sorted(
            {
                campo
                for c in encontradas
                for campo, valor in (c.value.get("contenido") or {}).items()
                if isinstance(valor, bool)
            }
        )
        for campo in campos:
            declarantes = [
                c
                for c in encontradas
                if (c.value.get("contenido") or {}).get(campo) not in SIN_DATO
            ]
            if declarantes and all(
                isinstance(c.value["contenido"][campo], bool) for c in declarantes
            ):
                _, _, del_campo = _resolver_booleano(declarantes, tipo, campo)
                conflictos.extend(del_campo)
    return conflictos


def best_found(claims: list[EvidenceInstance]) -> EvidenceInstance | None:
    """La afirmacion `encontrado=true` con mayor confianza, o `None` si ninguna declara el hecho.

    En empate decide el documento y despues el contenido, no el orden de la lista: el motor es
    deterministico (docs/00 §7) y dos corridas con la misma evidencia deben citar lo mismo.
    """

    encontradas = found(claims)
    return encontradas[0] if encontradas else None


def pattern_moment(pattern: EvidenceInstance | None, clave: str) -> datetime | None:
    """Marca de tiempo de un `log.pattern` (`desde`/`hasta`) como `datetime` en UTC.

    Devuelve `None` si el patron no la trae o no se puede leer: quien compare tiempos debe tratar
    ese caso como desconocido, no inventar un orden."""

    if pattern is None:
        return None
    valor = pattern.value.get(clave)
    if valor is None:
        return None
    try:
        momento = datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def latest_pattern(evidence: list[EvidenceInstance], patron: str) -> EvidenceInstance | None:
    """El `log.pattern` mas reciente de ese patron, por su `hasta`.

    Una ventana puede traer varias filas del mismo patron (un ejercicio fallido seguido de una
    restauracion verificada, dos escalamientos, ...). Quedarse con la primera haria que el veredicto
    dependiera del orden de ingesta: vale el ultimo estado que dejo la ventana. El desempate es
    determinista y no usa el `id` (docs/00 §7)."""

    candidatos = [e for e in by_type(evidence, "log.pattern") if e.value.get("patron") == patron]
    if not candidatos:
        return None
    sin_fecha = datetime.min.replace(tzinfo=UTC)
    return max(
        candidatos,
        key=lambda e: (
            pattern_moment(e, "hasta") or sin_fecha,
            pattern_moment(e, "desde") or sin_fecha,
            e.subject_ref,
            json.dumps(e.value, sort_keys=True, ensure_ascii=False),
        ),
    )


def result(
    criterion_id: str,
    estado: Estado,
    score: int | None,
    explanation: str,
    evidence_ids: list[str] | None = None,
) -> CriterionResult:
    """Construye un `CriterionResult`. `criterion_version` lo sobreescribe el motor con la version
    del catalogo (engine._evaluate_one)."""

    return CriterionResult(
        criterion_id=criterion_id,
        criterion_version=1,
        estado=estado,
        base_score=score,
        final_score=score,
        explanation=explanation,
        evidence_ids=evidence_ids or [],
    )


#: Lo que se agrega a la explicacion cuando los documentos callan (docs/09 §60).
SILENCIO_DOCUMENTAL = (
    " Sin una afirmacion explicita no se puede concluir que falte: no equivale a 0."
)

#: Marca que deja `marcar_sin_respuesta` cuando la IA no contesto parte del texto enviado
#: (docs/09 §100): una seccion sin respuesta no es un documento que calle.
AVISO_SIN_RESPUESTA = "la IA no respondio para"
SIN_RESPUESTA = (
    f"Limitacion: {AVISO_SIN_RESPUESTA} {{secciones}} seccion(es) de {{documentos}}; esa falta de"
    " respuesta no es silencio del documento y lo que no se pudo leer no se cuenta como ausencia."
)


def silencio_documental(
    criterion_id: str, explicacion: str, evidence_ids: list[str] | None = None
) -> CriterionResult:
    """Los documentos analizados no dicen lo que el criterio necesita (o lo marcan como no
    encontrado). Criterio conservador (docs/09 §60): que el texto calle no prueba que la practica
    falte -- la organizacion puede no haber subido ese documento --, asi que el resultado es
    `evidencia_insuficiente`, no 0. Antes daba 0 o insuficiente segun como respondiera el modelo
    (`encontrado: false` explicito u omitir el tipo). El hallazgo `limitacion` lo hace visible."""

    return result(
        criterion_id,
        Estado.EVIDENCIA_INSUFICIENTE,
        None,
        explicacion + SILENCIO_DOCUMENTAL,
        evidence_ids,
    )


def documentos_sin_respuesta(evidence: list[EvidenceInstance]) -> list[tuple[str, int]]:
    """Documentos con secciones que se enviaron a la IA y no tuvieron respuesta (docs/09 §100)."""

    pendientes: list[tuple[str, int]] = []
    for item in by_type(evidence, "doc.source.info"):
        secciones = item.value.get("sin_respuesta") or 0
        if secciones:
            pendientes.append((str(item.value.get("archivo") or item.subject_ref), int(secciones)))
    return pendientes


def es_silencio_documental(resultado: CriterionResult) -> bool:
    """La regla concluyo silencio documental, con o sin la limitacion de secciones sin responder."""

    return (
        resultado.explanation.endswith(SILENCIO_DOCUMENTAL)
        or AVISO_SIN_RESPUESTA in resultado.explanation
    )


def marcar_sin_respuesta(
    resultado: CriterionResult, evidence: list[EvidenceInstance]
) -> CriterionResult:
    """Un silencio por secciones que la IA no respondio no es silencio del documento (docs/09 §100).

    El motor lo aplica a todo resultado de regla, para que ninguna conclusion documental dependa de
    trozos que nadie llego a leer. Sigue siendo `evidencia_insuficiente`: no se convierte en 0 ni
    se inventa una ausencia."""

    if resultado.estado != Estado.EVIDENCIA_INSUFICIENTE:
        return resultado
    if not es_silencio_documental(resultado) or AVISO_SIN_RESPUESTA in resultado.explanation:
        return resultado
    pendientes = documentos_sin_respuesta(evidence)
    if not pendientes:
        return resultado
    detalle = SIN_RESPUESTA.format(
        secciones=sum(secciones for _, secciones in pendientes),
        documentos=", ".join(archivo for archivo, _ in pendientes),
    )
    conclusion = resultado.explanation.removesuffix(SILENCIO_DOCUMENTAL).strip()
    return resultado.model_copy(update={"explanation": f"{detalle} {conclusion}"})


#: Marca de la limitacion que deja `marcar_contradicciones` cuando un documento se contradice
#: sobre un booleano que el criterio uso (docs/09 §101).
AVISO_CONTRADICCION = "se contradice sobre"


def marcar_contradicciones(
    resultado: CriterionResult, evidence: list[EvidenceInstance]
) -> CriterionResult:
    """Hace visible que un documento se contradice sobre un booleano que el criterio uso.

    El motor lo aplica a todo resultado que cite alguna de las afirmaciones en conflicto. La
    explicacion dice que valor vale (el de la afirmacion mas confiable del documento) para que el
    puntaje no dependa de un fragmento que nego la practica sin que nadie lo note. No cambia el
    estado ni el puntaje: la regla ya resolvio con la misma regla que
    `contradicciones_booleanas`."""

    if resultado.estado in (Estado.ERROR, Estado.NO_APLICABLE) or not resultado.evidence_ids:
        return resultado
    citados = set(resultado.evidence_ids)
    pendientes = [
        c for c in contradicciones_booleanas(evidence) if citados.intersection(c.claim_ids)
    ]
    if not pendientes:
        return resultado
    detalle = "; ".join(
        f"el documento {c.archivo} {AVISO_CONTRADICCION} {c.campo} (vale"
        f" {'si' if c.valor else 'no'}, de la afirmacion mas confiable)"
        for c in pendientes
    )
    return resultado.model_copy(
        update={"explanation": f"{resultado.explanation} Limitacion: {detalle}."}
    )


def noting_unresolved(atributos: set[str]) -> Callable:
    """Decorador de `evaluate`: si el parser dejo expresiones sin resolver sobre los `atributos`
    que decide el criterio, el resultado lo declara como limitacion y cita esa evidencia
    (`tf.expression.unresolved`, docs/02 §4). El puntaje no cambia: se calcula sobre lo resuelto
    y la limitacion queda visible, igual que los recursos `unknown`."""

    def decorator(evaluate: Callable[[list[EvidenceInstance]], CriterionResult]) -> Callable:
        @wraps(evaluate)
        def wrapper(evidence: list[EvidenceInstance]) -> CriterionResult:
            resultado = evaluate(evidence)
            pendientes = [
                e
                for e in by_type(evidence, "tf.expression.unresolved")
                if e.value["atributo"] in atributos
            ]
            if not pendientes or resultado.estado == Estado.NO_APLICABLE:
                return resultado
            detalle = ", ".join(
                sorted({f"{e.value['recurso']}.{e.value['atributo']}" for e in pendientes})
            )
            return resultado.model_copy(
                update={
                    "explanation": (
                        f"{resultado.explanation} Limitacion: {len(pendientes)} expresion(es) sin"
                        f" resolver ({detalle}); el puntaje solo refleja lo resuelto."
                    ),
                    "evidence_ids": [*resultado.evidence_ids, *(e.id for e in pendientes)],
                }
            )

        return wrapper

    return decorator
