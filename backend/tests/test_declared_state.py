"""Estado declarado de la practica: negacion explicita y plan futuro (docs/01 §3, docs/09 §106).

Los documentos del estudio (`tests/fixtures/documents/estudio/`) son los casos que fallaban:
"no hay responsable de seguridad" se leia como `role_assigned` vigente y "se implementara en 2027"
como programa en marcha.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ai import extraction
from app.evaluation import engine
from app.evaluation.contradictions import detect
from app.evaluation.rules import pr02_backup
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents" / "estudio"
SCOPE = "entorno:produccion"


def _claim(
    tipo: str,
    contenido: dict,
    *,
    estado: str = "vigente",
    doc: str = "explicit-negations",
    cita: str = "texto del documento",
    confianza: float = 0.9,
) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=3,
        subject_type="document",
        subject_ref=f"doc:{doc}",
        scope=SCOPE,
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido,
            "encontrado": True,
            "confianza": confianza,
            "cita": cita,
            "estado_declarado": estado,
        },
        source_id="test:declared-state",
        locator=Locator(file=f"{doc}.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


def _backup(retencion: int, ref: str = "db-principal") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.backup.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref=ref,
        scope=SCOPE,
        value={"retencion_dias": retencion, "habilitado": True, "ventana": None},
        source_id="test:declared-state",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _encryption(ref: str = "db-principal") -> EvidenceInstance:
    return EvidenceInstance(
        type_id="tf.encryption.config",
        type_version=1,
        subject_type="aws_db_instance",
        subject_ref=ref,
        scope=SCOPE,
        value={"estado": "enabled", "mecanismo": "aws_kms", "llave": None},
        source_id="test:declared-state",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _evaluate(methodology, evidence, criterion_id):
    (resultado,) = engine.evaluate_only(methodology, evidence, [criterion_id])
    return resultado


# -- negacion explicita: ausencia, no silencio -------------------------------------------------


def test_an_explicit_negation_of_roles_scores_zero_not_75(methodology):
    """El documento dice "no hay un responsable designado para seguridad de la informacion"; la
    extraccion rellenaba el rol igual y la regla lo acreditaba."""

    texto = (FIXTURES / "explicit-negations.md").read_text(encoding="utf-8")
    negacion = "No hay un responsable designado para seguridad de la información"
    assert negacion in texto
    claim = _claim(
        "role_assigned",
        {
            "roles": [
                {
                    "rol": "jefe de TI",
                    "responsable": "jefe de TI",
                    "responsabilidades": "asume informalmente la seguridad",
                    "autoridad": "sin autoridad formal",
                }
            ]
        },
        estado="inexistente",
        cita=negacion,
    )

    resultado = _evaluate(methodology, [claim], "CRI-GV-02")

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0
    assert "no existe" in resultado.explanation
    assert "explicit-negations.md" in resultado.explanation
    assert resultado.evidence_ids == [claim.id]


def test_an_explicit_negation_of_the_recovery_procedure_scores_zero(methodology):
    texto = (FIXTURES / "explicit-negations.md").read_text(encoding="utf-8")
    negacion = "No hay un procedimiento documentado de respuesta a incidentes"
    assert negacion in texto
    claim = _claim(
        "process_defined",
        {
            "proceso": "recuperacion",
            "pasos": "No hay procedimiento documentado; se actua por intuicion",
        },
        estado="inexistente",
        cita=negacion,
    )

    resultado = _evaluate(methodology, [claim], "CRI-RC-01")

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0
    assert "no existe" in resultado.explanation


@pytest.mark.parametrize(
    ("criterion_id", "tipo", "contenido"),
    [
        ("CRI-GV-01", "policy_exists", {"nombre": "Politica de seguridad"}),
        ("CRI-GV-03", "risk_tolerance", {"objetivos_riesgo": "reducir el riesgo"}),
        ("CRI-GV-04", "policy_review", {"frecuencia": "anual"}),
        ("CRI-GV-05", "org_context", {"mision": "pagos"}),
        ("CRI-GV-06", "supplier_program", {"programa": True}),
        ("CRI-ID-04", "data_inventory", {"tipos_datos": ["datos personales"]}),
        ("CRI-PR-07", "training_program", {"programa": True}),
        ("CRI-RS-01", "process_defined", {"proceso": "respuesta", "pasos": "no existe"}),
        ("CRI-RS-03", "notification_list", {"destinatarios": ["cliente"]}),
    ],
)
def test_the_central_helper_applies_the_negation_to_every_doc_claim_rule(
    methodology, criterion_id, tipo, contenido
):
    claim = _claim(tipo, contenido, estado="inexistente")

    resultado = _evaluate(methodology, [claim], criterion_id)

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0
    assert "El documento" in resultado.explanation


def test_a_negation_in_the_same_document_does_not_contribute_its_fields(methodology):
    """Un documento que afirma la practica en un fragmento y la niega en otro no puede sumar los
    campos de la negacion: `merged_content` los agregaba y la negacion, con mas datos, subia el
    puntaje aunque §101 deja el valor de la afirmacion mas confiable (docs/09 §114)."""

    vigente = _claim(
        "process_defined",
        {"proceso": "recuperacion", "pasos": "restaurar el backup y verificar"},
        doc="mismo-documento",
        cita="El procedimiento de recuperacion describe los pasos de restauracion",
    )
    negacion = _claim(
        "process_defined",
        {
            "proceso": "recuperacion",
            "pasos": "restaurar el backup",
            "criterios_activacion": "caida mayor a cuatro horas",
            "responsables": "equipo de infraestructura",
        },
        estado="inexistente",
        doc="mismo-documento",
        cita="No existe un procedimiento documentado de recuperacion",
    )

    resultado = _evaluate(methodology, [vigente, negacion], "CRI-RC-01")

    assert resultado.final_score == 75
    assert resultado.evidence_ids == [vigente.id]


def test_a_more_reliable_negation_in_the_same_document_still_denies_a_boolean(methodology):
    """Excluir la negacion de `found` no puede subir el puntaje de un documento que se contradice:
    su `false` explicito sigue compitiendo con la afirmacion vigente y, si es la mas confiable,
    gana (docs/09 §101, §114)."""

    contenido = {
        "roles": [
            {
                "rol": "CISO",
                "responsable": "Ana",
                "responsabilidades": "seguridad",
                "autoridad": "aprueba excepciones",
            }
        ],
        "recursos_asignados": True,
        "practicas_rh": True,
    }
    solo = _claim("role_assigned", contenido, doc="mismo-documento", confianza=0.8)
    vigente = _claim("role_assigned", contenido, doc="mismo-documento", confianza=0.8)
    negacion = _claim(
        "role_assigned",
        {"recursos_asignados": False},
        estado="inexistente",
        doc="mismo-documento",
        confianza=0.95,
        cita="No se han asignado recursos al area de seguridad",
    )

    sin_negacion = _evaluate(methodology, [solo], "CRI-GV-02")
    con_negacion = _evaluate(methodology, [vigente, negacion], "CRI-GV-02")

    assert con_negacion.final_score < sin_negacion.final_score
    assert "se contradice" in con_negacion.explanation


# -- plan declarado: no acredita la practica de hoy --------------------------------------------


def test_a_planned_supplier_program_is_not_credited(methodology):
    texto = (FIXTURES / "planned-not-implemented.md").read_text(encoding="utf-8")
    plan = (
        "En el primer semestre de 2027 se implementará un programa formal de gestión de proveedores"
    )
    assert plan in texto
    claim = _claim(
        "supplier_program",
        {"programa": True},
        estado="planificado",
        doc="planned-not-implemented",
        cita=plan,
    )

    resultado = _evaluate(methodology, [claim], "CRI-GV-06")

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0
    assert "planificada" in resultado.explanation
    assert "2027" in resultado.explanation


def test_a_planned_training_program_is_not_credited(methodology):
    claim = _claim(
        "training_program",
        {"programa": True, "frecuencia": "anual"},
        estado="planificado",
        doc="planned-not-implemented",
        cita="La formación en seguridad se implementará en 2027",
    )

    resultado = _evaluate(methodology, [claim], "CRI-PR-07")

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0


def test_a_plan_does_not_credit_a_claim_that_only_says_there_is_no_program(methodology):
    """La extraccion puede dejar dos afirmaciones del mismo tipo: una planificada y otra vigente
    que en realidad declara que no hay programa. El plan no suma el campo que la vigente niega."""

    plan = _claim(
        "training_program",
        {"programa": True, "frecuencia": "anual"},
        estado="planificado",
        doc="planned-not-implemented",
        cita="La formación en seguridad se implementará en 2027",
    )
    actual = _claim(
        "training_program",
        {"programa": False, "frecuencia": "anual"},
        estado="vigente",
        doc="planned-not-implemented",
        cita="actualmente solo se envía un correo anual con recomendaciones",
    )

    resultado = _evaluate(methodology, [plan, actual], "CRI-PR-07")

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0


def test_a_current_practice_in_another_document_still_counts_against_a_plan(methodology):
    """Un plan en un documento no borra la practica vigente que declara otro."""

    practica = {
        "programa": True,
        "roles": True,
        "integracion_riesgo": True,
        "proveedores_priorizados": True,
        "requisitos_contractuales": True,
        "debida_diligencia": True,
        "riesgos_monitoreados": True,
    }
    plan = _claim("supplier_program", {"programa": True}, estado="planificado", doc="plan-2027")
    vigente = _claim("supplier_program", practica, estado="vigente", doc="politica-proveedores")

    resultado = _evaluate(methodology, [plan, vigente], "CRI-GV-06")
    referencia = _evaluate(methodology, [vigente], "CRI-GV-06")

    assert resultado.final_score == referencia.final_score


# -- documento-vs-documento: se registran ambos y ninguno cuenta -------------------------------


def test_absence_in_one_document_and_practice_in_another_is_a_visible_contradiction(methodology):
    ausencia = _claim("role_assigned", {"roles": []}, estado="inexistente", doc="diagnostico")
    vigente = _claim(
        "role_assigned",
        {
            "roles": [
                {
                    "rol": "CISO",
                    "responsable": "Ana",
                    "responsabilidades": "seguridad",
                    "autoridad": "aprobacion",
                }
            ],
            "recursos_asignados": True,
            "practicas_rh": True,
        },
        estado="vigente",
        doc="politica-roles",
    )

    contradicciones = detect([ausencia, vigente])
    de_gv02 = [c for c in contradicciones if c.criterion_id == "CRI-GV-02"]
    assert len(de_gv02) == 1
    assert set(de_gv02[0].evidence_ids) == {ausencia.id, vigente.id}
    assert set(de_gv02[0].excluded_claim_ids) == {ausencia.id, vigente.id}

    resultado = _evaluate(methodology, [ausencia, vigente], "CRI-GV-02")

    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE
    assert "Contradiccion entre fuentes" in resultado.explanation


@pytest.mark.parametrize(
    ("criterion_id", "tipo", "contenido"),
    [
        ("CRI-DE-02", "process_defined", {"proceso": "analisis incidentes"}),
        ("CRI-RC-02", "backup_policy", {"respaldo": False}),
        ("CRI-RS-01", "process_defined", {"proceso": "respuesta"}),
        ("CRI-RS-04", "process_defined", {"proceso": "contencion"}),
    ],
)
def test_a_plan_that_a_rule_cannot_credit_ends_in_zero_not_silence(
    methodology, criterion_id, tipo, contenido
):
    """Reglas mixtas devolvian `evidencia_insuficiente` sin citar nada: la planificacion quedaba
    invisible. Ahora citan la afirmacion y el resultado es 0."""

    claim = _claim(tipo, contenido, estado="planificado")

    resultado = _evaluate(methodology, [claim], criterion_id)

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0


# -- cantidades en palabras --------------------------------------------------------------------


def test_retention_written_with_words_scores_like_digits(methodology):
    """PR-02 leia la retencion con `(\\d+)`: "noventa dias" quedaba sin numero y el criterio en
    75 aunque la politica declarara 90 dias."""

    texto = (FIXTURES / "numbers-in-words.md").read_text(encoding="utf-8")
    cita = "Los respaldos de la base de datos se conservan durante noventa días."
    assert cita in texto
    con_palabras = _claim(
        "backup_policy", {"respaldo": True, "retencion": "noventa días"}, cita=cita
    )
    con_digitos = _claim("backup_policy", {"respaldo": True, "retencion": "90 días"}, cita=cita)
    tecnico = [_backup(90), _encryption()]

    assert pr02_backup.retencion_politica_dias(con_palabras) == 90
    resultado = _evaluate(methodology, [*tecnico, con_palabras], "CRI-PR-02")
    referencia = _evaluate(methodology, [*tecnico, con_digitos], "CRI-PR-02")

    assert resultado.final_score == referencia.final_score == 100


# -- faceta del proceso: negar "otro" no niega respuesta ni riesgos (docs/09 §108) ------------


def test_a_denied_process_does_not_zero_another_process_criterion(methodology):
    """En la corrida 1 de mid, una negacion de `process_defined` con proceso "otro" en
    respuesta-incidentes hacia que la contradiccion excluyera tambien el proceso de respuesta y
    el de riesgos, que si estaban declarados."""

    respuesta = _claim(
        "process_defined",
        {
            "proceso": "respuesta",
            "pasos": "triaje inicial, clasificacion del impacto y contencion",
            "responsables": "equipo de guardia",
        },
        doc="respuesta-incidentes",
    )
    negacion = _claim(
        "process_defined", {"proceso": "recuperacion"}, estado="inexistente", doc="otro-documento"
    )

    assert [c for c in detect([respuesta, negacion]) if c.criterion_id == "CRI-RS-01"] == []
    resultado = _evaluate(methodology, [respuesta, negacion], "CRI-RS-01")

    assert resultado.estado == Estado.EVALUADO
    assert resultado.final_score is not None and resultado.final_score > 0


def test_a_denied_process_of_the_same_facet_in_another_document_is_still_a_contradiction(
    methodology,
):
    respuesta = _claim("process_defined", {"proceso": "respuesta", "pasos": "triaje"}, doc="manual")
    negacion = _claim(
        "process_defined", {"proceso": "respuesta"}, estado="inexistente", doc="diagnostico"
    )

    contradicciones = [c for c in detect([respuesta, negacion]) if c.criterion_id == "CRI-RS-01"]
    assert len(contradicciones) == 1
    assert set(contradicciones[0].excluded_claim_ids) == {respuesta.id, negacion.id}

    resultado = _evaluate(methodology, [respuesta, negacion], "CRI-RS-01")
    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE


# -- corrida 1 de mid: valores reales de la evidencia guardada (docs/09 §108) ------------------


TEXTO_GOBIERNO = (
    "No hay todavia un inventario de los servicios criticos de los que dependen los clientes ni de"
    " las dependencias externas de la operacion; el equipo de arquitectura lo tiene como pendiente."
)
TEXTO_RIESGOS = (
    "El inventario de activos incluye: aws_db_instance (bases de datos de clientes y de reportes) y"
    " aws_s3_bucket (documentos y exportes). Una vez al ano el responsable de seguridad identifica"
    " las amenazas principales con cada area, estima su impacto y acuerda las medidas a tomar."
)
TEXTO_RESPUESTA = (
    "Todavia no hay un procedimiento escrito de erradicacion ni una lista de pasos acordada. El"
    " equipo de guardia hace el triaje inicial, clasifica el incidente por su impacto y aplica las"
    " medidas de contencion."
)


def _claims_from_raw(doc: str, texto: str, afirmaciones: list[dict]) -> list[EvidenceInstance]:
    return extraction._claims_from_raw(
        {"afirmaciones": afirmaciones},
        chunk_text=texto,
        chunk_locator=Locator(file=f"{doc}.md"),
        tipos_solicitados=["data_inventory", "process_defined"],
        doc_id=doc,
        source_id="test:mid",
        scope=SCOPE,
        confianza_minima=0.6,
    )


def _mid_run_1_claims() -> list[EvidenceInstance]:
    """Las afirmaciones de `e_mid_1.json` que hacian caer ID-01/03/04 y RS-01."""

    return [
        *_claims_from_raw(
            "gobierno-y-proveedores",
            TEXTO_GOBIERNO,
            [
                {
                    "tipo": "data_inventory",
                    "encontrado": True,
                    "estado_declarado": "inexistente",
                    "contenido": {},
                    "cita": {"fragmento": TEXTO_GOBIERNO},
                    "confianza": 0.9,
                }
            ],
        ),
        *_claims_from_raw(
            "riesgos-e-inventario",
            TEXTO_RIESGOS,
            [
                {
                    "tipo": "data_inventory",
                    "encontrado": True,
                    "estado_declarado": "vigente",
                    "contenido": {
                        "activos": ["aws_db_instance", "aws_s3_bucket"],
                        "tipos_datos": ["nombres", "correos", "cifras de ventas"],
                    },
                    "cita": {"fragmento": TEXTO_RIESGOS.split(" Una vez")[0]},
                    "confianza": 0.9,
                },
                {
                    "tipo": "process_defined",
                    "encontrado": True,
                    "estado_declarado": "vigente",
                    "contenido": {
                        "proceso": "riesgos",
                        "impactos": True,
                        "responsables": "responsable de seguridad",
                    },
                    "cita": {"fragmento": TEXTO_RIESGOS.split(" Una vez al ano ")[1]},
                    "confianza": 0.9,
                },
            ],
        ),
        *_claims_from_raw(
            "respuesta-incidentes",
            TEXTO_RESPUESTA,
            [
                {
                    "tipo": "process_defined",
                    "encontrado": True,
                    "estado_declarado": "inexistente",
                    "contenido": {"proceso": "otro"},
                    "cita": {"fragmento": TEXTO_RESPUESTA.split(" El equipo")[0]},
                    "confianza": 0.9,
                },
                {
                    "tipo": "process_defined",
                    "encontrado": True,
                    "estado_declarado": "vigente",
                    "contenido": {
                        "proceso": "respuesta",
                        "pasos": "triaje inicial, clasificacion del impacto y contencion",
                        "responsables": "equipo de guardia y responsable de seguridad",
                    },
                    "cita": {"fragmento": TEXTO_RESPUESTA.split(" El equipo")[1]},
                    "confianza": 0.9,
                },
            ],
        ),
    ]


def test_mid_run_1_spurious_denials_are_discarded_before_scoring():
    claims = _mid_run_1_claims()

    assert {c.value["tipo_afirmacion"] for c in claims} == {"data_inventory", "process_defined"}
    assert not [c for c in claims if c.value["estado_declarado"] == "inexistente"]
    assert {
        c.value["contenido"].get("proceso") for c in claims if "proceso" in c.value["contenido"]
    } == {
        "respuesta",
        "riesgos",
    }


@pytest.mark.parametrize("criterion_id", ["CRI-ID-01", "CRI-ID-03", "CRI-ID-04", "CRI-RS-01"])
def test_mid_run_1_inventory_and_process_criteria_are_not_left_without_evidence(
    methodology, criterion_id
):
    resultado = _evaluate(methodology, _mid_run_1_claims(), criterion_id)

    assert resultado.estado == Estado.EVALUADO
    assert resultado.final_score is not None


# -- faceta de la politica: negar la de proveedores no niega la de seguridad (docs/09 §109) -----

TEXTO_POLITICA_PROVEEDORES = (
    "No existe por ahora un programa ni una politica de gestion del riesgo de proveedores"
)
TEXTO_POLITICA_SEGURIDAD = (
    "La presente Politica de Seguridad de la Informacion fue aprobada por la Direccion General el"
    " 15 de marzo de 2025 y aplica a todos los sistemas y empleados de la organizacion."
)


def _mid_run_1_policy_claims() -> list[EvidenceInstance]:
    """Las dos `policy_exists` de `e_mid_1.json` que dejaban GV-01 en `evidencia_insuficiente`."""

    return [
        _claim(
            "policy_exists",
            {"nombre": "politica de gestion del riesgo de proveedores"},
            estado="inexistente",
            doc="gobierno-y-proveedores",
            cita=TEXTO_POLITICA_PROVEEDORES,
            confianza=0.8,
        ),
        _claim(
            "policy_exists",
            {
                "nombre": "Politica de Seguridad de la Informacion",
                "aprobada_por": "Direccion General",
            },
            doc="politica-seguridad",
            cita=TEXTO_POLITICA_SEGURIDAD,
            confianza=0.95,
        ),
    ]


def test_a_denied_supplier_policy_does_not_sink_the_security_policy_criterion(methodology):
    proveedores, seguridad = _mid_run_1_policy_claims()

    assert [c for c in detect([proveedores, seguridad]) if c.criterion_id == "CRI-GV-01"] == []

    resultado = _evaluate(methodology, [proveedores, seguridad], "CRI-GV-01")

    assert resultado.estado == Estado.EVALUADO
    assert resultado.final_score == 75
    assert seguridad.id in resultado.evidence_ids


def test_a_denied_policy_with_the_same_name_in_another_document_is_still_a_contradiction(
    methodology,
):
    _, seguridad = _mid_run_1_policy_claims()
    negacion = seguridad.model_copy(
        update={
            "subject_ref": "doc:diagnostico",
            "locator": Locator(file="diagnostico.md"),
            "value": {**seguridad.value, "estado_declarado": "inexistente"},
        }
    )

    contradicciones = [c for c in detect([negacion, seguridad]) if c.criterion_id == "CRI-GV-01"]
    assert len(contradicciones) == 1
    assert set(contradicciones[0].excluded_claim_ids) == {negacion.id, seguridad.id}

    resultado = _evaluate(methodology, [negacion, seguridad], "CRI-GV-01")
    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE


def test_a_bare_denial_of_the_policy_still_scores_zero(methodology):
    """Sin nombre, la negacion habla de "una politica" en general: no hay politica que acreditar."""

    negacion = _claim(
        "policy_exists",
        {},
        estado="inexistente",
        doc="diagnostico",
        cita="No existe una politica de seguridad",
    )

    resultado = _evaluate(methodology, [negacion], "CRI-GV-01")

    assert resultado.estado == Estado.NO_IMPLEMENTADO
    assert resultado.final_score == 0


def test_a_bare_denial_contradicts_any_named_policy(methodology):
    """Una negacion sin nombre dice que no hay politica alguna: contradice a la nombrada."""

    _, seguridad = _mid_run_1_policy_claims()
    negacion = _claim("policy_exists", {}, estado="inexistente", doc="diagnostico")

    assert len([c for c in detect([negacion, seguridad]) if c.criterion_id == "CRI-GV-01"]) == 1

    resultado = _evaluate(methodology, [negacion, seguridad], "CRI-GV-01")
    assert resultado.estado == Estado.EVIDENCIA_INSUFICIENTE
