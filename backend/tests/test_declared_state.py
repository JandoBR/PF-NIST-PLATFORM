"""Estado declarado de la practica: negacion explicita y plan futuro (docs/01 §3, docs/09 §106).

Los documentos del estudio (`tests/fixtures/documents/estudio/`) son los casos que fallaban:
"no hay responsable de seguridad" se leia como `role_assigned` vigente y "se implementara en 2027"
como programa en marcha.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

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
