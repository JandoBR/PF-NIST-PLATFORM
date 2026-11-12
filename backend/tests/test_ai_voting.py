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


def test_a_three_way_tie_in_a_closed_field_leaves_it_absent():
    claims = vote(
        [
            [_claim(contenido={"frecuencia": "anual", "aprobada_por": "Direccion"})],
            [_claim(contenido={"frecuencia": "mensual", "aprobada_por": "Direccion"})],
            [_claim(contenido={"frecuencia": "semestral"})],
        ]
    )

    (claim,) = claims
    assert "frecuencia" not in claim.value["contenido"]  # campo cerrado: tres valores distintos
    assert claim.value["contenido"]["aprobada_por"] == "Direccion"  # texto libre en 2 de 3


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
    activos = claim.value["contenido"]["activos"]
    assert [a.casefold().strip() for a in activos] == ["s3", "rds"]  # ec2/lambda: una corrida
    assert (
        vote(
            [
                [_claim(contenido={"activos": ["s3", "lambda"]})],
                [_claim(contenido={"activos": ["s3", "RDS "]})],
                [_claim(contenido={"activos": ["s3", "rds", "ec2"]})],
            ]
        )[0].value["contenido"]["activos"]
        == activos
    )


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


def _proceso(**contenido):
    return {"proceso": "riesgos", **contenido}


def test_free_text_survives_when_it_is_paraphrased():
    """`pasos` es texto libre que la regla solo mira como presencia: tres redacciones distintas
    apoyan el campo y el valor guardado es una de ellas (el medoide), no una concatenacion."""

    textos = [
        "identificar amenazas por activo y estimar impacto y probabilidad",
        "se identifican amenazas por activo, se estima el impacto y la probabilidad",
        "identificar las amenazas de cada activo y estimar su impacto y probabilidad",
    ]
    claims = vote(
        [[_claim(tipo="process_defined", contenido=_proceso(pasos=texto))] for texto in textos]
    )

    (claim,) = claims
    pasos = claim.value["contenido"]["pasos"]
    assert pasos in textos


def test_free_text_that_only_one_run_produced_does_not_survive():
    claims = vote(
        [
            [_claim(tipo="process_defined", contenido=_proceso(pasos="paso uno, paso dos"))],
            [_claim(tipo="process_defined", contenido=_proceso(registro_riesgos=True))],
            [_claim(tipo="process_defined", contenido=_proceso(registro_riesgos=True))],
        ]
    )

    (claim,) = claims
    assert "pasos" not in claim.value["contenido"]
    assert claim.value["contenido"]["registro_riesgos"] is True


def test_free_text_uses_the_majority_of_the_claim_group():
    claims = vote(
        [
            [_claim(tipo="process_defined", contenido=_proceso(responsables="el CISO"))],
            [_claim(tipo="process_defined", contenido=_proceso(responsables="CISO y guardia"))],
            [_claim(tipo="process_defined", contenido=_proceso(metricas=True))],
        ]
    )

    (claim,) = claims
    assert claim.value["contenido"]["responsables"] in {"el CISO", "CISO y guardia"}


def test_the_medoid_is_the_most_central_wording_and_is_order_independent():
    textos = [
        "aplica cambios de emergencia en produccion",
        "aplica los cambios de emergencia en produccion",
        "cambios de emergencia en produccion",
    ]
    runs = [
        [_claim(tipo="process_defined", contenido=_proceso(responsables=texto))] for texto in textos
    ]

    valores = set()
    for permutacion in ([2, 0, 1], [1, 2, 0], [0, 1, 2]):
        claims = vote([runs[indice] for indice in permutacion])
        valores.add(claims[0].value["contenido"]["responsables"])
    assert len(valores) == 1
    assert valores.pop() in textos[:2]  # no elige la redaccion corta, que se parece menos al resto


def test_vote_is_order_independent_including_citation_and_list_order():
    runs = [
        [_claim(confianza=0.9, cita="cita a", contenido={"activos": ["s3", "rds"]})],
        [_claim(confianza=0.9, cita="cita b", contenido={"activos": ["rds", "s3", "ec2"]})],
        [_claim(confianza=0.9, cita="cita c", contenido={"activos": ["s3", "rds"]})],
    ]

    primero = [c.model_dump() for c in vote(runs)]
    for permutacion in ([2, 1, 0], [1, 0, 2], [0, 2, 1]):
        assert [c.model_dump() for c in vote([runs[i] for i in permutacion])] == primero


def test_list_items_are_matched_with_tolerant_similarity():
    claims = vote(
        [
            [_claim(contenido={"activos": ["aws_s3_bucket", "aws_db_instance"]})],
            [_claim(contenido={"activos": ["s3", "aws_db_instance (base de datos)"]})],
            [_claim(contenido={"activos": ["aws_s3_bucket (documentos)"]})],
        ]
    )

    (claim,) = claims
    activos = claim.value["contenido"]["activos"]
    assert len(activos) == 2  # el bucket y la base sobreviven en sus formas parecidas
    assert any("s3" in texto.casefold() for texto in activos)
    assert any("db_instance" in texto.casefold() for texto in activos)


def test_list_items_that_only_one_run_produced_do_not_survive():
    claims = vote(
        [
            [_claim(contenido={"activos": ["aws_s3_bucket", "aws_lambda_function"]})],
            [_claim(contenido={"activos": ["aws_s3_bucket", "aws_db_instance"]})],
            [_claim(contenido={"activos": ["aws_s3_bucket", "aws_ec2_instance"]})],
        ]
    )

    (claim,) = claims
    activos = [texto.casefold() for texto in claim.value["contenido"]["activos"]]
    assert not any(
        "lambda" in texto or "db_instance" in texto or "ec2" in texto for texto in activos
    )


def test_roles_are_matched_by_role_name_and_each_subfield_is_voted():
    """Tres redacciones del mismo rol: el nombre se empareja por parecido y responsable,
    responsabilidades y autoridad se votan por presencia (docs/09 §113)."""

    roles = [
        {
            "rol": "Oficial de Seguridad de la Informacion (CISO)",
            "responsable": "Marta Quintero",
            "responsabilidades": "programa de seguridad",
            "autoridad": "detener despliegues",
        },
        {
            "rol": "CISO",
            "responsable": "Marta Quintero",
            "responsabilidades": "coordinar el programa de seguridad",
            "autoridad": "detener los despliegues que incumplan la politica",
        },
        {
            "rol": "Responsable de seguridad de la informacion",
            "responsable": "M. Quintero",
            "responsabilidades": "programa de seguridad y respuesta",
        },
    ]
    claims = vote([[_claim(tipo="role_assigned", contenido={"roles": [role]})] for role in roles])

    (claim,) = claims
    (rol,) = claim.value["contenido"]["roles"]
    assert rol["responsable"] == "Marta Quintero"
    assert "seguridad" in rol["responsabilidades"]
    # la autoridad solo la declaran 2 de 3: sobrevive, con el texto mas central
    assert "detener" in rol["autoridad"]


def test_a_role_that_only_one_run_produced_does_not_survive():
    cis = {
        "rol": "CISO",
        "responsable": "Marta Quintero",
        "responsabilidades": "programa",
        "autoridad": "detener despliegues",
    }
    infra = {
        "rol": "Jefe de Infraestructura",
        "responsable": "Luis Paredes",
        "responsabilidades": "servidores",
        "autoridad": "cambios de emergencia",
    }
    claims = vote(
        [
            [_claim(tipo="role_assigned", contenido={"roles": [cis, infra]})],
            [_claim(tipo="role_assigned", contenido={"roles": [cis]})],
            [_claim(tipo="role_assigned", contenido={"roles": [cis]})],
        ]
    )

    (claim,) = claims
    (rol,) = claim.value["contenido"]["roles"]
    assert rol["rol"] == "CISO"


def test_criticality_list_of_objects_matches_by_asset():
    claims = vote(
        [
            [
                _claim(
                    tipo="data_inventory",
                    contenido={
                        "criticidad": [
                            {"activo": "aws_db_instance", "nivel": "alta"},
                            {"activo": "aws_s3_bucket", "nivel": "media"},
                        ]
                    },
                )
            ],
            [
                _claim(
                    tipo="data_inventory",
                    contenido={
                        "criticidad": [
                            {"activo": "aws_db_instance (clientes)", "nivel": "alto"},
                            {"activo": "aws_s3_bucket (documentos)", "nivel": "media"},
                        ]
                    },
                )
            ],
            [
                _claim(
                    tipo="data_inventory",
                    contenido={"criticidad": [{"activo": "aws_db_instance", "nivel": "alta"}]},
                )
            ],
        ]
    )

    (claim,) = claims
    criticidad = claim.value["contenido"]["criticidad"]
    activos = [item["activo"].casefold() for item in criticidad]
    assert len(activos) == 2
    assert any("db_instance" in activo for activo in activos)
    assert any("s3_bucket" in activo for activo in activos)


def test_number_and_duration_fields_keep_exact_normalized_semantics():
    claims = vote(
        [
            [_claim(tipo="backup_policy", contenido={"respaldo": True, "retencion": "7 dias"})],
            [_claim(tipo="backup_policy", contenido={"respaldo": True, "retencion": " 7 dias "})],
            [_claim(tipo="backup_policy", contenido={"respaldo": True, "retencion": "30 dias"})],
        ]
    )

    (claim,) = claims
    assert claim.value["contenido"]["retencion"] == "7 dias"


def test_paraphrased_number_is_not_merged_because_extraction_normalizes_it_first():
    """El voto compara la cantidad ya normalizada por `numbers.py`: "siete dias" y "7 dias" solo
    coinciden si la extraccion los normalizo antes (docs/05 §2.3 E5)."""

    claims = vote(
        [
            [_claim(tipo="backup_policy", contenido={"respaldo": True, "retencion": "7 dias"})],
            [_claim(tipo="backup_policy", contenido={"respaldo": True, "retencion": "siete dias"})],
            [_claim(tipo="backup_policy", contenido={"respaldo": True, "retencion": "7 dias"})],
        ]
    )

    (claim,) = claims
    assert claim.value["contenido"]["retencion"] == "7 dias"


def test_every_field_that_the_prompt_declares_has_a_voting_class():
    from app.ai.extraction import _CONTENT_FIELDS
    from app.ai.voting import _CAMPOS_POR_TIPO

    assert set(_CONTENT_FIELDS) <= set(_CAMPOS_POR_TIPO)
