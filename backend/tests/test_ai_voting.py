"""Votacion por mayoria de las corridas de U1 (docs/05 §2.4, docs/09 §105)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai.voting import umbral, vote, votes
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(
    *,
    tipo: str = "policy_exists",
    contenido: dict | None = None,
    encontrado: bool = True,
    confianza: float = 0.9,
    cita: str = "cita",
    locator: Locator | None = None,
    estado: str | None = "vigente",
) -> EvidenceInstance:
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=3,
        subject_type="document",
        subject_ref="doc:d",
        scope="entorno:produccion",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido or {},
            "encontrado": encontrado,
            "confianza": confianza,
            "cita": cita,
            "estado_declarado": estado,
        },
        source_id="test:doc",
        locator=locator or Locator(file="d.md", section="S"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        created_by="ai:extraction",
    )


def test_majority_value_wins_and_the_minority_field_disappears():
    claims = vote(
        [
            [_claim(contenido={"nombre": "Politica", "aprobada_por": "Direccion"})],
            [_claim(contenido={"nombre": "politica ", "aprobada_por": "Direccion"})],
            [_claim(contenido={"nombre": "Otra cosa", "aprobada_por": "TI"})],
        ]
    )

    (claim,) = claims
    assert claim.value["contenido"] == {"nombre": "Politica", "aprobada_por": "Direccion"}


def test_case_and_surrounding_spaces_are_the_same_value():
    claims = vote(
        [
            [_claim(contenido={"frecuencia": "Anual"})],
            [_claim(contenido={"frecuencia": "anual"})],
            [_claim(contenido={"frecuencia": "mensual"})],
        ]
    )

    assert claims[0].value["contenido"]["frecuencia"] == "Anual"


def test_a_three_way_tie_leaves_the_field_absent():
    claims = vote(
        [
            [_claim(contenido={"nombre": "A", "aprobada_por": "Direccion"})],
            [_claim(contenido={"nombre": "B", "aprobada_por": "Direccion"})],
            [_claim(contenido={"nombre": "C"})],
        ]
    )

    (claim,) = claims
    assert "nombre" not in claim.value["contenido"]
    assert claim.value["contenido"]["aprobada_por"] == "Direccion"  # en 2 de 3: mayoria


def test_null_and_absent_are_the_same_state():
    claims = vote(
        [
            [_claim(contenido={"retencion": None, "respaldo": True})],
            [_claim(contenido={"respaldo": True})],
            [_claim(contenido={"retencion": "7 dias", "respaldo": True})],
        ]
    )

    (claim,) = claims
    assert "retencion" not in claim.value["contenido"]  # null/ausente gana 2 a 1
    assert claim.value["contenido"]["respaldo"] is True


def test_list_elements_need_a_majority_and_keep_a_deterministic_order():
    claims = vote(
        [
            [_claim(contenido={"activos": ["s3", "rds", "ec2"]})],
            [_claim(contenido={"activos": ["s3", "RDS "]})],
            [_claim(contenido={"activos": ["s3", "lambda"]})],
        ]
    )

    (claim,) = claims
    assert claim.value["contenido"]["activos"] == ["s3", "rds"]  # ec2 solo en una corrida


def test_process_defined_is_clustered_by_proceso_not_just_tipo():
    respuesta = {"proceso": "respuesta", "metricas": True}
    mejora = {"proceso": "mejora", "planes_actualizados": True}
    claims = vote(
        [
            [_claim(tipo="process_defined", contenido=respuesta)],
            [
                _claim(tipo="process_defined", contenido=respuesta),
                _claim(tipo="process_defined", contenido=mejora),
            ],
            [
                _claim(tipo="process_defined", contenido=respuesta),
                _claim(tipo="process_defined", contenido=mejora),
            ],
        ]
    )

    por_proceso = {c.value["contenido"]["proceso"]: c for c in claims}
    assert set(por_proceso) == {"respuesta", "mejora"}
    assert por_proceso["mejora"].value["contenido"]["planes_actualizados"] is True


def test_three_processes_survive_even_when_every_run_emits_all_of_them():
    """El prompt v7 pide una afirmacion por proceso (docs/09 §111): respuesta, analisis y mejora
    se votan por separado y cada uno conserva sus propios campos, sin fusionarse ni perderse."""

    respuesta = {"proceso": "respuesta", "pasos": "triaje y escalamiento"}
    analisis = {"proceso": "analisis incidentes", "pasos": "causa raiz y evidencia"}
    mejora = {"proceso": "mejora", "metricas": True, "ajustes": True}
    claims = vote(
        [
            [
                _claim(tipo="process_defined", contenido=respuesta),
                _claim(tipo="process_defined", contenido=analisis),
                _claim(tipo="process_defined", contenido=mejora),
            ]
            for _ in range(3)
        ]
    )

    por_proceso = {c.value["contenido"]["proceso"]: c.value["contenido"] for c in claims}
    assert set(por_proceso) == {"respuesta", "analisis incidentes", "mejora"}
    assert por_proceso["respuesta"] == respuesta
    assert por_proceso["analisis incidentes"] == analisis
    assert por_proceso["mejora"] == mejora


def test_citation_and_locator_come_from_the_highest_confidence_run():
    locators = [Locator(file="d.md", section=f"S{indice}") for indice in range(1, 4)]
    claims = vote(
        [
            [_claim(confianza=0.7, cita="cita 1", locator=locators[0])],
            [_claim(confianza=0.95, cita="cita 2", locator=locators[1])],
            [_claim(confianza=0.8, cita="cita 3", locator=locators[2])],
        ]
    )

    (claim,) = claims
    assert claim.value["cita"] == "cita 2"
    assert claim.locator.section == "S2"
    assert claim.value["confianza"] == 0.8  # mediana de las corridas que lo apoyan


def test_a_claim_that_only_one_run_found_does_not_survive():
    claims = vote(
        [
            [_claim(tipo="backup_policy", contenido={"respaldo": True})],
            [],
            [],
        ]
    )

    assert claims == []


def test_an_unusable_claim_still_survives_visible_with_its_limitations():
    """E3/E8: no vota, pero no se borra si la mayoria de las corridas lo produjo."""

    from app.ai.extraction import CITA_NO_LOCALIZABLE

    unusable = _claim(confianza=0.3)
    unusable = unusable.model_copy(update={"limitations": CITA_NO_LOCALIZABLE})
    claims = vote([[unusable], [unusable], [unusable]])

    (claim,) = claims
    assert claim.limitations == CITA_NO_LOCALIZABLE


def test_estado_declarado_is_voted_as_a_closed_field():
    """La negacion es parte de la afirmacion: dos corridas `inexistente` ganan a una `vigente`."""

    claims = vote(
        [
            [_claim(contenido={"programa": False}, estado="inexistente")],
            [_claim(contenido={"programa": False}, estado="inexistente")],
            [_claim(contenido={"programa": False}, estado="vigente")],
        ]
    )

    (claim,) = claims
    assert claim.value["estado_declarado"] == "inexistente"


def test_estado_declarado_does_not_vote_mixed_with_an_invalid_value():
    """Un valor fuera de la lista cerrada no es un estado: no arrastra el voto."""

    claims = vote(
        [
            [_claim(estado="planificado")],
            [_claim(estado="planificado")],
            [_claim(estado="PENDIENTE")],
        ]
    )

    (claim,) = claims
    assert claim.value["estado_declarado"] == "planificado"


def test_boolean_and_enum_values_are_compared_exactly():
    claims = vote(
        [
            [_claim(contenido={"priorizacion": True, "frecuencia": "anual"})],
            [_claim(contenido={"priorizacion": "true", "frecuencia": "anual"})],
            [_claim(contenido={"priorizacion": False, "frecuencia": "mensual"})],
        ]
    )

    (claim,) = claims
    # Un booleano escrito como texto no es el mismo valor: solo la frecuencia tiene mayoria.
    assert "priorizacion" not in claim.value["contenido"]
    assert claim.value["contenido"]["frecuencia"] == "anual"


def test_the_vote_threshold_is_a_strict_majority():
    assert umbral(1) == 1
    assert umbral(2) == 2
    assert umbral(3) == 2
    assert umbral(4) == 3
    assert umbral(5) == 3


def test_u1_votes_is_configurable_and_invalid_values_fall_back(monkeypatch):
    monkeypatch.delenv("U1_VOTES", raising=False)
    assert votes() == 3
    monkeypatch.setenv("U1_VOTES", "5")
    assert votes() == 5
    monkeypatch.setenv("U1_VOTES", "0")
    assert votes() == 1
    monkeypatch.setenv("U1_VOTES", "muchas")
    assert votes() == 3
