"""Informes en PDF (docs/11 AMP-02): el informe ejecutivo de una evaluacion y la comparacion entre
dos. Separa el acceso a la herramienta del acceso a los resultados: el PDF se entrega a quien no usa
la plataforma.

Solo renderiza datos ya calculados (agregados, Tier, hallazgos, planes): no puntua ni decide nada,
asi que el PDF nunca puede diferir de lo que muestran la API y la UI. Usa las fuentes PDF estandar
(Helvetica, WinAnsi): cubre el espanol; evitar simbolos fuera de Latin-1 en los textos.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.evaluation.schemas import CriterionResult
from app.recommendations.findings import Finding
from app.recommendations.plans import Plan
from app.schemas.assessment import AssessmentDetail, ComparisonOut

FUNCTION_NAMES = {
    "GV": "Gobernar",
    "ID": "Identificar",
    "PR": "Proteger",
    "DE": "Detectar",
    "RS": "Responder",
    "RC": "Recuperar",
}
_FUNCTION_ORDER = list(FUNCTION_NAMES)
_TIER_LABELS = ["Parcial", "Informado sobre riesgos", "Repetible", "Adaptativo"]
_SEVERIDAD_ORDEN = {"alta": 0, "media": 1, "baja": 2}
_PRIORIDAD_ORDEN = {"alta": 0, "media": 1, "baja": 2}
_MAX_PLANES = 10
_MAX_LIMITACIONES = 10

_INK = colors.HexColor("#1f2933")
_MUTED = colors.HexColor("#616e7c")
_ACCENT = colors.HexColor("#0b5cad")
_HEADER_BG = colors.HexColor("#e4eaf1")
_ROW_ALT = colors.HexColor("#f5f7fa")
_WARN = colors.HexColor("#b45309")

_styles = getSampleStyleSheet()
_BODY = ParagraphStyle("body", parent=_styles["BodyText"], fontSize=9.5, leading=13, textColor=_INK)
_SMALL = ParagraphStyle("small", parent=_BODY, fontSize=8, leading=10.5, textColor=_MUTED)
_CELL = ParagraphStyle("cell", parent=_BODY, fontSize=8.5, leading=10.5)
_CELL_BOLD = ParagraphStyle("cellb", parent=_CELL, fontName="Helvetica-Bold")
_TITLE = ParagraphStyle(
    "title", parent=_styles["Title"], fontSize=19, leading=23, alignment=0, textColor=_ACCENT
)
_H2 = ParagraphStyle(
    "h2",
    parent=_styles["Heading2"],
    fontSize=12.5,
    leading=15,
    spaceBefore=14,
    spaceAfter=6,
    textColor=_INK,
)
_WARN_STYLE = ParagraphStyle("warn", parent=_BODY, textColor=_WARN)


def _p(text: object, style: ParagraphStyle = _BODY) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _score(value: float | None) -> str:
    return "N/D" if value is None else f"{value:g}"


def _pct(value: float | None) -> str:
    return "N/D" if value is None else f"{value:.0%}"


#: Como en la UI: `no_implementado` incluye fallas observadas, no solo "no implementado".
_ESTADO_LABELS = {"no_implementado": "ausente o fallido"}

#: Que le paso a un criterio entre dos evaluaciones (`CriterionDiff.direccion`).
_DIRECCION_LABELS = {
    "mejora": "Mejoro",
    "retroceso": "Empeoro",
    "ahora_evaluado": "Ahora se evalua",
    "dejo_de_evaluarse": "Dejo de evaluarse",
    "cambio_de_estado": "Cambio de estado",
    "criterio_nuevo": "Nuevo en el catalogo",
    "criterio_retirado": "Ya no esta en el catalogo",
    "igual": "Sin cambio",
}
#: Primero lo que empeoro, como en la pantalla.
_DIRECCION_ORDER = (
    "retroceso",
    "dejo_de_evaluarse",
    "mejora",
    "ahora_evaluado",
    "cambio_de_estado",
    "criterio_retirado",
    "criterio_nuevo",
    "igual",
)


def _estado(value: str | None) -> str:
    if value is None:
        return "-"
    return _ESTADO_LABELS.get(value, value.replace("_", " "))


def _fecha(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _table(rows: list[list], widths: Sequence[float], *, align_right: Sequence[int] = ()) -> Table:
    table = Table(rows, colWidths=list(widths), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd2d9")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
    ]
    style += [("ALIGN", (c, 0), (c, -1), "RIGHT") for c in align_right]
    table.setStyle(TableStyle(style))
    return table


def _head(*labels: str) -> list[Paragraph]:
    return [_p(label, _CELL_BOLD) for label in labels]


def _footer(titulo: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(2 * cm, 1.2 * cm, titulo)
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Pagina {doc.page}")
        canvas.restoreState()

    return draw


def _build(story: list, footer: str, title: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=2 * cm,
        title=title,
        author="Plataforma de evaluacion NIST CSF",
    )
    draw = _footer(footer)
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buffer.getvalue()


def _tier_text(detail: AssessmentDetail) -> str:
    tier = detail.tier
    if tier.tier is None:
        return "No estimable"
    label = _TIER_LABELS[tier.tier - 1] if 1 <= tier.tier <= len(_TIER_LABELS) else tier.nombre
    suffix = " (provisional)" if tier.provisional else ""
    return f"Nivel {tier.tier} - {label}{suffix}"


def build_executive_report(
    detail: AssessmentDetail,
    results: list[CriterionResult],
    titulos: dict[str, str],
    findings: list[Finding],
    plans: list[Plan],
    documents: Sequence[dict] = (),
) -> bytes:
    """Informe ejecutivo de una evaluacion: resumen, madurez por funcion, hallazgos y plan.
    `documents` son los `value` de `doc.source.info` (documentos analizados, docs/11 CR-07)."""

    width = A4[0] - 4 * cm
    story: list = [
        _p("Informe ejecutivo de madurez en ciberseguridad", _TITLE),
        _p("Evaluacion segun NIST Cybersecurity Framework 2.0", _SMALL),
        Spacer(1, 8),
        _table(
            [
                [_p("Organizacion", _CELL_BOLD), _p(detail.org_nombre, _CELL)],
                [_p("Alcance", _CELL_BOLD), _p(detail.scope, _CELL)],
                [_p("Fecha de la evaluacion", _CELL_BOLD), _p(_fecha(detail.creado_en), _CELL)],
                [_p("Metodologia", _CELL_BOLD), _p(detail.methodology_version, _CELL)],
                [_p("Evaluacion", _CELL_BOLD), _p(detail.id, _CELL)],
            ],
            [4.5 * cm, width - 4.5 * cm],
        ),
        _p("Resumen", _H2),
        _table(
            [
                _head("Puntaje global", "Cobertura", "Tier estimado"),
                [
                    _p(_score(detail.score_global), _CELL_BOLD),
                    _p(_pct(detail.cobertura_global), _CELL),
                    _p(_tier_text(detail), _CELL_BOLD),
                ],
            ],
            [width * 0.25, width * 0.25, width * 0.5],
        ),
        Spacer(1, 6),
        _p(detail.tier.justificacion),
    ]
    if detail.provisional_global:
        story += [
            Spacer(1, 4),
            _p(
                "Puntaje provisional: la cobertura es baja, por lo que el puntaje no es "
                "representativo de toda la organizacion.",
                _WARN_STYLE,
            ),
        ]
    if detail.tier.faltantes:
        story += [
            Spacer(1, 4),
            _p("Para el siguiente nivel falta: " + "; ".join(detail.tier.faltantes)),
        ]

    por_funcion = {a.ref: a for a in detail.agregados_funcion}
    filas = [_head("Funcion", "Puntaje", "Cobertura", "Estado")]
    for ref in [*_FUNCTION_ORDER, *sorted(set(por_funcion) - set(_FUNCTION_ORDER))]:
        agg = por_funcion.get(ref)
        if agg is None:
            continue
        filas.append(
            [
                _p(f"{ref} - {FUNCTION_NAMES.get(ref, ref)}", _CELL),
                _p(_score(agg.score), _CELL_BOLD),
                _p(_pct(agg.cobertura), _CELL),
                _p("Provisional" if agg.provisional else "", _CELL),
            ]
        )
    story += [
        _p("Madurez por funcion", _H2),
        _table(filas, [width * 0.4, width * 0.2, width * 0.2, width * 0.2], align_right=(1, 2)),
    ]

    brechas = sorted(
        (f for f in findings if f.tipo == "brecha"),
        key=lambda f: (_SEVERIDAD_ORDEN.get(f.severidad, 9), f.score or 0),
    )
    contradicciones = [f for f in findings if f.tipo == "contradiccion"]
    story.append(_p("Hallazgos prioritarios", _H2))
    if brechas:
        story.append(
            _table(
                [
                    _head("Criterio", "Hallazgo", "Severidad", "Puntaje"),
                    *[
                        [
                            _p(f.criterion_id, _CELL),
                            _p(f.titulo, _CELL),
                            _p(f.severidad, _CELL),
                            _p(_score(f.score), _CELL_BOLD),
                        ]
                        for f in brechas
                    ],
                ],
                [width * 0.17, width * 0.53, width * 0.15, width * 0.15],
                align_right=(3,),
            )
        )
    else:
        story.append(_p("No hay criterios por debajo del umbral de brecha."))
    if contradicciones:
        story += [Spacer(1, 8), _p("Contradicciones entre fuentes", _CELL_BOLD)]
        for c in contradicciones:
            story.append(_p(f"{c.criterion_id} ({c.severidad}): {c.detalle or c.titulo}", _BODY))
            story.append(Spacer(1, 3))

    limitaciones = [f for f in findings if f.tipo == "limitacion"]
    if limitaciones:
        story += [
            Spacer(1, 8),
            _p("Limitaciones del analisis", _CELL_BOLD),
            _p(
                "Lo que no se pudo determinar. No son brechas ni cambian el puntaje, pero esos "
                "criterios deben leerse con cautela.",
                _SMALL,
            ),
        ]
        for f in limitaciones[:_MAX_LIMITACIONES]:
            story.append(_p(f"{f.criterion_id}: {f.titulo}", _BODY))
        if len(limitaciones) > _MAX_LIMITACIONES:
            story.append(
                _p(f"... y {len(limitaciones) - _MAX_LIMITACIONES} mas en la plataforma.", _SMALL)
            )

    story.append(_p("Plan de accion recomendado", _H2))
    abiertos = sorted(
        (p for p in plans if p.estado != "hecho"),
        key=lambda p: _PRIORIDAD_ORDEN.get(p.prioridad, 9),
    )
    if abiertos:
        story.append(
            _table(
                [
                    _head("Prioridad", "Criterio", "Accion"),
                    *[
                        [
                            _p(p.prioridad, _CELL),
                            _p(p.criterion_id, _CELL),
                            _p(f"{p.titulo}. {p.objetivo}", _CELL),
                        ]
                        for p in abiertos[:_MAX_PLANES]
                    ],
                ],
                [width * 0.14, width * 0.17, width * 0.69],
            )
        )
        if len(abiertos) > _MAX_PLANES:
            story += [
                Spacer(1, 3),
                _p(f"... y {len(abiertos) - _MAX_PLANES} plan(es) mas en la plataforma.", _SMALL),
            ]
    else:
        story.append(_p("No hay planes abiertos para esta evaluacion."))

    if documents:
        story.append(_p("Documentos analizados", _H2))
        story.append(
            _table(
                [
                    _head("Documento", "Secciones", "Analizadas", "Sin analizar"),
                    *[
                        [
                            _p(d["archivo"], _CELL),
                            _p(d["secciones"], _CELL),
                            _p(d["analizadas"], _CELL),
                            _p(d["omitidas"] + d.get("sin_respuesta", 0), _CELL),
                        ]
                        for d in documents
                    ],
                ],
                [width * 0.52, width * 0.16, width * 0.16, width * 0.16],
                align_right=(1, 2, 3),
            )
        )
        if any(d["omitidas"] or d.get("sin_respuesta") for d in documents):
            story += [
                Spacer(1, 3),
                _p(
                    "Hay secciones sin analizar (tope por documento o sin respuesta de la IA): "
                    "lo que digan no esta reflejado en los puntajes.",
                    _SMALL,
                ),
            ]

    story += [_p("Resultados por criterio", _H2)]
    filas = [_head("Criterio", "Descripcion", "Estado", "Puntaje")]
    for r in sorted(results, key=lambda r: r.criterion_id):
        filas.append(
            [
                _p(r.criterion_id, _CELL),
                _p(titulos.get(r.criterion_id, r.criterion_id), _CELL),
                _p(r.estado.value.replace("_", " "), _CELL),
                _p(_score(r.final_score), _CELL_BOLD),
            ]
        )
    story.append(
        _table(
            filas,
            [width * 0.15, width * 0.5, width * 0.22, width * 0.13],
            align_right=(3,),
        )
    )

    story += [
        _p("Notas", _H2),
        _p(
            "Los puntajes van de 0 a 100. Un criterio sin evidencia suficiente no puntua y "
            "reduce la cobertura; no equivale a un incumplimiento. La evidencia tecnica "
            "prevalece sobre la documental cuando se contradicen, y un criterio con una "
            "contradiccion sin resolver no puede subir su puntaje respecto a la evaluacion "
            "anterior.",
            _SMALL,
        ),
    ]
    ai = (detail.reproducibility or {}).get("ai")
    if ai:
        pasos = ", ".join(k for k in ("extraccion", "ajuste", "planes") if k in ai)
        story.append(
            _p(f"En esta evaluacion participo la IA (modelo {ai.get('modelo')}): {pasos}.", _SMALL)
        )
    return _build(
        story,
        f"{detail.org_nombre} - informe ejecutivo - {detail.scope}",
        f"Informe ejecutivo - {detail.org_nombre}",
    )


def build_comparison_report(
    comparison: ComparisonOut,
    antes: AssessmentDetail,
    despues: AssessmentDetail,
) -> bytes:
    """Comparacion entre dos evaluaciones (A = antes, B = despues)."""

    width = A4[0] - 4 * cm
    delta = (
        None
        if comparison.global_antes is None or comparison.global_despues is None
        else comparison.global_despues - comparison.global_antes
    )
    delta_text = "N/D" if delta is None else f"{delta:+g}"
    story: list = [
        _p("Comparacion de evaluaciones", _TITLE),
        _p("NIST Cybersecurity Framework 2.0", _SMALL),
        Spacer(1, 8),
        _table(
            [
                _head("", "Antes", "Despues"),
                [
                    _p("Organizacion", _CELL_BOLD),
                    _p(antes.org_nombre, _CELL),
                    _p(despues.org_nombre, _CELL),
                ],
                [_p("Alcance", _CELL_BOLD), _p(antes.scope, _CELL), _p(despues.scope, _CELL)],
                [
                    _p("Fecha", _CELL_BOLD),
                    _p(_fecha(antes.creado_en), _CELL),
                    _p(_fecha(despues.creado_en), _CELL),
                ],
                [
                    _p("Puntaje global", _CELL_BOLD),
                    _p(_score(comparison.global_antes), _CELL_BOLD),
                    _p(_score(comparison.global_despues), _CELL_BOLD),
                ],
                [
                    _p("Cobertura de evidencia", _CELL_BOLD),
                    _p(_pct(antes.cobertura_global), _CELL),
                    _p(_pct(despues.cobertura_global), _CELL),
                ],
                [
                    _p("Tier estimado", _CELL_BOLD),
                    _p(_tier_text(antes), _CELL),
                    _p(_tier_text(despues), _CELL),
                ],
            ],
            [4.4 * cm, (width - 4.4 * cm) / 2, (width - 4.4 * cm) / 2],
        ),
        Spacer(1, 6),
        _p(f"Cambio en el puntaje global: {delta_text}", _BODY),
    ]
    if not comparison.misma_metodologia or not comparison.mismo_scope:
        motivos = [
            texto
            for distinto, texto in (
                (not comparison.misma_metodologia, "versiones distintas de la metodologia"),
                (not comparison.mismo_scope, "alcances distintos"),
            )
            if distinto
        ]
        story.append(
            _p(
                f"Atencion: las dos evaluaciones usan {' y '.join(motivos)}. Parte de los cambios"
                " puede deberse a eso y no a cambios en el entorno.",
                _SMALL,
            )
        )
        if not comparison.misma_metodologia:
            # Misma trampa que en pantalla: la cobertura de evidencia se calcula sobre el
            # catalogo de cada evaluacion, asi que al crecer el catalogo "baja" sin que haya
            # empeorado nada.
            story.append(
                _p(
                    "La cobertura de evidencia se mide sobre el catalogo de cada evaluacion: si"
                    " cambio de tamano, su diferencia no es comparable.",
                    _SMALL,
                )
            )

    # Hallazgos que dejaron de aparecer o son nuevos.
    if comparison.hallazgos_resueltos or comparison.hallazgos_nuevos:
        partes = []
        if comparison.hallazgos_resueltos:
            partes.append("ya no aparecen: " + ", ".join(comparison.hallazgos_resueltos))
        if comparison.hallazgos_nuevos:
            partes.append("nuevos: " + ", ".join(comparison.hallazgos_nuevos))
        story.append(_p("Hallazgos - " + "; ".join(partes) + ".", _BODY))
        if any(d.direccion == "dejo_de_evaluarse" for d in comparison.diffs):
            story.append(
                _p(
                    "Un hallazgo tambien deja de aparecer cuando su criterio deja de poder"
                    " evaluarse; no significa que se haya corregido.",
                    _SMALL,
                )
            )

    # Madurez por funcion: los mismos agregados (ponderados) que el informe ejecutivo.
    antes_f = {a.ref: a for a in antes.agregados_funcion}
    despues_f = {a.ref: a for a in despues.agregados_funcion}
    refs = [r for r in _FUNCTION_ORDER if r in antes_f or r in despues_f]
    refs += sorted((set(antes_f) | set(despues_f)) - set(_FUNCTION_ORDER))
    if refs:
        filas = [_head("Funcion", "Puntaje antes", "Puntaje despues", "Cobertura")]
        for ref in refs:
            a, d = antes_f.get(ref), despues_f.get(ref)
            filas.append(
                [
                    _p(f"{ref} - {FUNCTION_NAMES.get(ref, ref)}", _CELL),
                    _p(_score(a.score if a else None), _CELL),
                    _p(_score(d.score if d else None), _CELL_BOLD),
                    _p(
                        f"{_pct(a.cobertura if a else None)} > {_pct(d.cobertura if d else None)}",
                        _CELL,
                    ),
                ]
            )
        story += [
            _p("Cambio por funcion", _H2),
            _table(
                filas,
                [width * 0.37, width * 0.2, width * 0.2, width * 0.23],
                align_right=(1, 2),
            ),
        ]

    cambios = sorted(
        (d for d in comparison.diffs if d.cambio),
        key=lambda d: (_DIRECCION_ORDER.index(d.direccion), d.criterion_id),
    )
    story.append(_p(f"Criterios que cambiaron ({len(cambios)})", _H2))
    if cambios:
        filas = [_head("Criterio", "Descripcion", "Estado", "Puntaje", "Cambio")]
        for d in cambios:
            filas.append(
                [
                    _p(d.criterion_id, _CELL),
                    _p(d.titulo, _CELL),
                    _p(f"{_estado(d.estado_antes)} > {_estado(d.estado_despues)}", _CELL),
                    _p(f"{_score(d.score_antes)} > {_score(d.score_despues)}", _CELL),
                    _p(_DIRECCION_LABELS.get(d.direccion, d.direccion), _CELL_BOLD),
                ]
            )
        story.append(
            _table(
                filas,
                [width * 0.14, width * 0.30, width * 0.24, width * 0.14, width * 0.18],
            )
        )

        # El porque de cada cambio: la explicacion del criterio en cada evaluacion.
        story.append(_p("Por que cambio cada criterio", _H2))
        for d in cambios:
            # Cada criterio va entero en una pagina: el titulo no se separa de su explicacion.
            story.append(
                KeepTogether(
                    [
                        _p(f"{d.criterion_id} - {d.titulo}", _CELL_BOLD),
                        _p(f"Antes: {d.explicacion_antes or 'sin resultado'}", _SMALL),
                        _p(f"Despues: {d.explicacion_despues or 'sin resultado'}", _SMALL),
                        Spacer(1, 5),
                    ]
                )
            )
    else:
        story.append(_p("Ningun criterio cambio entre las dos evaluaciones."))

    sin_cambio = len(comparison.diffs) - len(cambios)
    story += [Spacer(1, 8), _p(f"Criterios sin cambio: {sin_cambio}.", _SMALL)]
    return _build(
        story,
        f"{despues.org_nombre} - comparacion de evaluaciones - {despues.scope}",
        f"Comparacion de evaluaciones - {despues.org_nombre}",
    )
