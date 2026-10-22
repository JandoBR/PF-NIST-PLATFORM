"""Comparacion entre evaluaciones: que le paso a cada criterio y por que (docs/09 §67)."""

from __future__ import annotations

from pathlib import Path

from app.core import assessment_service as svc
from app.core import comparison
from app.core.comparison import CriterionDiff
from app.models.tables import CriterionResultRow

DEMO = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"


def _diff(estado_antes, score_antes, estado_despues, score_despues) -> CriterionDiff:
    return CriterionDiff("CRI-X", "x", estado_antes, estado_despues, score_antes, score_despues)


def test_direction_tells_scoring_changes_from_evidence_changes():
    assert _diff("evaluado", 25, "evaluado", 75).direccion == comparison.MEJORA
    assert _diff("evaluado", 75, "no_implementado", 0).direccion == comparison.RETROCESO
    # Pasar de no tener puntaje a tenerlo no es mejorar: es que ahora hay con que evaluarlo.
    insuficiente = "evidencia_insuficiente"
    assert _diff(insuficiente, None, "evaluado", 75).direccion == comparison.AHORA_EVALUADO
    assert _diff("evaluado", 75, insuficiente, None).direccion == comparison.DEJO_DE_EVALUARSE
    assert _diff(insuficiente, None, "no_aplicable", None).direccion == comparison.CAMBIO_DE_ESTADO
    assert _diff("evaluado", 75, "evaluado", 75).direccion == comparison.IGUAL


def test_a_criterion_missing_on_one_side_is_a_catalog_change_not_an_environment_change():
    """Comparar dos evaluaciones de catalogos distintos (una oleada de criterios de por medio).

    Sin esto, un criterio que no existia antes sale como "cambio de estado" con dos guiones a
    cada lado: no dice nada y se lee como si algo hubiera cambiado en la infraestructura.
    """

    insuficiente = "evidencia_insuficiente"
    assert _diff(None, None, insuficiente, None).direccion == comparison.CRITERIO_NUEVO
    assert _diff(None, None, "evaluado", 75).direccion == comparison.CRITERIO_NUEVO
    assert _diff(insuficiente, None, None, None).direccion == comparison.CRITERIO_RETIRADO
    assert _diff("evaluado", 75, None, None).direccion == comparison.CRITERIO_RETIRADO


def test_comparing_across_catalog_versions_marks_only_the_new_criteria(db_session, methodology):
    """Un criterio que solo esta en el catalogo nuevo no inventa un cambio en el resto."""

    antes = _run(db_session, methodology, "gaps")
    despues = _run(db_session, methodology, "gaps")

    # Simula el catalogo anterior: la evaluacion "antes" se queda sin el resultado de CRI-RS-04,
    # que es justo lo que pasa al comparar contra una evaluacion anterior a su oleada.
    assert "CRI-RS-04" in methodology.criterios
    db_session.query(CriterionResultRow).filter(
        CriterionResultRow.assessment_id == antes.id,
        CriterionResultRow.criterion_id == "CRI-RS-04",
    ).delete()
    db_session.commit()

    report = comparison.compare(db_session, methodology, antes.id, despues.id)
    por_id = {d.criterion_id: d for d in report.diffs}

    assert por_id["CRI-RS-04"].direccion == comparison.CRITERIO_NUEVO
    assert [d.criterion_id for d in report.cambios] == ["CRI-RS-04"]


def _run(db_session, methodology, paquete: str, scope: str = "entorno:produccion"):
    return svc.run_assessment(
        db_session,
        methodology,
        org_name="Org Comparar",
        scope=scope,
        terraform_path=DEMO / paquete / "terraform",
        ansible_path=DEMO / paquete / "ansible",
    )


def test_compare_explains_each_change_between_two_demo_bundles(db_session, methodology):
    antes = _run(db_session, methodology, "gaps")
    despues = _run(db_session, methodology, "mid")

    report = comparison.compare(db_session, methodology, antes.id, despues.id)
    por_id = {d.criterion_id: d for d in report.diffs}

    assert por_id["CRI-PR-03"].direccion == comparison.MEJORA  # SSH/RDP ya no estan abiertos
    assert por_id["CRI-PR-06"].direccion == comparison.AHORA_EVALUADO  # ahora hay CloudTrail
    assert por_id["CRI-PR-05"].direccion == comparison.DEJO_DE_EVALUARSE  # bucket sin bloque
    assert por_id["CRI-PR-01"].direccion == comparison.IGUAL

    pr03 = por_id["CRI-PR-03"]
    assert "expuestos a Internet" in pr03.explicacion_antes
    assert "Ningun security group expone" in pr03.explicacion_despues

    assert report.misma_metodologia and report.mismo_scope
    assert report.hallazgos_resueltos == ["CRI-PR-02", "CRI-PR-03", "CRI-PR-05"]
    assert report.hallazgos_nuevos == []


def test_compare_flags_a_different_scope_or_methodology(db_session, methodology):
    antes = _run(db_session, methodology, "gaps")
    despues = _run(db_session, methodology, "gaps", scope="entorno:pruebas")
    antes.methodology_version = "criterios=8,tipos=4,settings=2"
    db_session.commit()

    report = comparison.compare(db_session, methodology, antes.id, despues.id)
    assert not report.mismo_scope and not report.misma_metodologia
