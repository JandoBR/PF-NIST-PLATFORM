from dataclasses import replace
from pathlib import Path

from app.api import routes_assessments
from app.core import assessment_service as svc
from app.core import comparison
from app.core.repository import result_to_row
from app.evaluation.schemas import CriterionResult, Estado

TF_GOOD = Path(__file__).resolve().parent / "fixtures" / "terraform" / "good"


def _changed_weights(methodology):
    criteria = dict(methodology.criterios)
    criteria["CRI-PR-01"] = criteria["CRI-PR-01"].model_copy(update={"peso": 100})
    return replace(methodology, criterios=criteria)


def test_detail_uses_the_assessment_methodology_snapshot(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Historical detail",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
    )
    expected = routes_assessments._assessment_detail(db_session, methodology, assessment)

    actual = routes_assessments._assessment_detail(
        db_session, _changed_weights(methodology), assessment
    )

    assert actual.score_global == expected.score_global
    assert actual.agregados_funcion == expected.agregados_funcion
    assert actual.agregados_categoria == expected.agregados_categoria
    assert actual.tier == expected.tier


def test_legacy_unknown_criterion_does_not_break_detail(db_session, methodology):
    assessment = svc.run_assessment(
        db_session,
        methodology,
        org_name="Legacy detail",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
    )
    assessment.reproducibility = None
    db_session.add(
        result_to_row(
            assessment.id,
            CriterionResult(
                criterion_id="CRI-REMOVED-99",
                criterion_version=1,
                estado=Estado.EVALUADO,
                base_score=100,
                final_score=100,
                explanation="from an old catalog",
            ),
        )
    )
    db_session.commit()

    detail = routes_assessments._assessment_detail(db_session, methodology, assessment)

    assert detail.score_global is not None
    assert all(a.ref != "CRI-REMOVED-99" for a in detail.agregados_categoria)


def test_comparison_uses_each_assessment_snapshot(db_session, methodology):
    first = svc.run_assessment(
        db_session,
        methodology,
        org_name="Historical comparison",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
    )
    second = svc.run_assessment(
        db_session,
        methodology,
        org_name="Historical comparison",
        scope="entorno:produccion",
        terraform_path=TF_GOOD,
    )
    expected = comparison.compare(db_session, methodology, first.id, second.id)

    actual = comparison.compare(db_session, _changed_weights(methodology), first.id, second.id)

    assert actual.global_antes == expected.global_antes
    assert actual.global_despues == expected.global_despues
    assert actual.diffs == expected.diffs
