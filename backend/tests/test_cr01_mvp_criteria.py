"""Reglas de los 7 criterios MVP agregados en CR-01 (docs/11 §C, docs/03)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.evaluation import engine
from app.evaluation.rules import (
    de01_monitoring,
    gv02_roles,
    gv03_risk_tolerance,
    id01_asset_inventory,
    id02_asset_criticality,
    id03_risk_assessment,
    rc01_recovery_procedure,
)
from app.evaluation.schemas import Estado
from app.schemas.evidence import EvidenceInstance, Locator, Modality


def _claim(tipo: str, contenido: dict | None = None, encontrado: bool = True, **kw):
    return EvidenceInstance(
        type_id="doc.claim",
        type_version=1,
        subject_type="document",
        subject_ref="doc:politica",
        scope="s",
        value={
            "tipo_afirmacion": tipo,
            "contenido": contenido or {},
            "encontrado": encontrado,
            "confianza": kw.get("confianza", 0.9),
        },
        source_id="src",
        locator=Locator(file="politica.md"),
        observed_at=datetime.now(UTC),
        modality=Modality.DOCUMENTAL,
        limitations=kw.get("limitations"),
        created_by="ai:extraction",
    )


def _tf_logging(habilitado=True, multi_region=None, destino=None):
    return EvidenceInstance(
        type_id="tf.logging.config",
        type_version=1,
        subject_type="resource",
        subject_ref="aws_cloudtrail.main",
        scope="s",
        value={"habilitado": habilitado, "multi_region": multi_region, "destino": destino},
        source_id="src",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _tf_resource(tipo):
    return EvidenceInstance(
        type_id="tf.resource.present",
        type_version=1,
        subject_type="resource",
        subject_ref=f"{tipo}.x",
        scope="s",
        value={"tipo": tipo, "nombre": "x", "entorno": None},
        source_id="src",
        locator=Locator(file="main.tf"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="terraform",
    )


def _syslog(estado="habilitado"):
    return EvidenceInstance(
        type_id="an.service.state",
        type_version=1,
        subject_type="host",
        subject_ref="all",
        scope="s",
        value={"servicio": "rsyslog", "estado": estado},
        source_id="src",
        locator=Locator(file="hardening.yml"),
        observed_at=datetime.now(UTC),
        modality=Modality.DECLARADA,
        created_by="ansible",
    )


# --- CRI-GV-02 ---


def test_gv02_sin_claims_es_insuficiente():
    assert gv02_roles.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


def test_gv02_rol_completo_con_recursos_y_practicas_rh_es_100():
    evidence = [
        _claim(
            "role_assigned",
            {
                "roles": [
                    {
                        "rol": "CISO",
                        "responsable": "Ana Perez",
                        "responsabilidades": "aprobar politicas y supervisar riesgos",
                        "autoridad": "aprobar excepciones",
                    }
                ],
                "recursos_asignados": True,
                "practicas_rh": True,
            },
        )
    ]
    result = gv02_roles.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVALUADO, 100)


def test_gv02_nombrar_un_ciso_no_es_dotar_la_funcion():
    """GV.RR-03/04: con autoridad pero sin recursos ni practicas de RH, el tope es 75."""

    evidence = [_claim("role_assigned", {"roles": [{"rol": "CISO", "autoridad": "aprobar"}]})]

    result = gv02_roles.evaluate(evidence)

    assert result.final_score == 75
    assert "GV.RR-03" in result.explanation and "GV.RR-04" in result.explanation


def test_gv02_responsable_sin_responsabilidades_es_75():
    evidence = [
        _claim(
            "role_assigned",
            {"roles": [{"rol": "CISO", "responsable": "Ana Perez", "autoridad": "aprobar"}]},
        )
    ]
    assert gv02_roles.evaluate(evidence).final_score == 75


def test_gv02_sin_autoridad_es_50():
    evidence = [
        _claim(
            "role_assigned",
            {
                "roles": [
                    {
                        "rol": "CISO",
                        "responsable": "Ana Perez",
                        "responsabilidades": "supervisar riesgos",
                    }
                ]
            },
        )
    ]
    assert gv02_roles.evaluate(evidence).final_score == 50


def test_gv02_rol_sin_responsable_es_75():
    evidence = [_claim("role_assigned", {"roles": [{"rol": "CISO", "autoridad": "aprobar"}]})]
    assert gv02_roles.evaluate(evidence).final_score == 75


def test_gv02_rol_generico_sin_responsable_es_50():
    evidence = [_claim("role_assigned", {"roles": [{"rol": "el area de TI"}]})]
    assert gv02_roles.evaluate(evidence).final_score == 50


def test_gv02_elige_el_rol_completo_entre_varios():
    evidence = [
        _claim(
            "role_assigned",
            {
                "roles": [
                    {"rol": "CISO", "autoridad": "aprobar"},
                    {
                        "rol": "DPO",
                        "responsable": "Luis Gomez",
                        "responsabilidades": "vigilar datos personales",
                        "autoridad": "bloquear tratamientos",
                    },
                ],
                "recursos_asignados": True,
                "practicas_rh": True,
            },
        )
    ]
    assert gv02_roles.evaluate(evidence).final_score == 100


def test_gv02_las_practicas_de_otro_fragmento_completan_el_rol():
    """El rol completo y las practicas de GV.RR-03/04 pueden caer en fragmentos distintos del
    mismo documento; antes solo contaba el fragmento elegido por su rol."""

    rol = _claim(
        "role_assigned",
        {
            "roles": [
                {
                    "rol": "CISO",
                    "responsable": "Ana Torres",
                    "responsabilidades": "programa de seguridad",
                    "autoridad": "aprobar excepciones",
                }
            ]
        },
        confianza=0.95,
    )
    practicas = _claim(
        "role_assigned", {"recursos_asignados": True, "practicas_rh": True}, confianza=0.7
    )

    result = gv02_roles.evaluate([practicas, rol])

    assert result.final_score == 100
    assert set(result.evidence_ids) == {rol.id, practicas.id}


def test_gv02_no_declarado_es_insuficiente_no_0():
    """Conservador (docs/09 §60): que los documentos callen no prueba que no haya roles."""

    evidence = [_claim("role_assigned", {}, encontrado=False)]
    result = gv02_roles.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVIDENCIA_INSUFICIENTE, None)
    assert "no equivale a 0" in result.explanation


# --- CRI-GV-03 ---


def test_gv03_estrategia_desarrollada_es_100():
    evidence = [
        _claim(
            "risk_tolerance",
            {
                "objetivos_riesgo": "x",
                "tolerancia": "baja",
                "integracion_empresarial": True,
                "metodo_estandarizado": True,
                "lineas_comunicacion": True,
            },
        )
    ]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 100


def test_gv03_objetivos_y_tolerancia_sin_estrategia_es_75():
    """GV.RM tiene siete resultados: fijar objetivos y tolerancia cubre dos."""

    evidence = [_claim("risk_tolerance", {"objetivos_riesgo": "x", "tolerancia": "baja"})]

    result = gv03_risk_tolerance.evaluate(evidence)

    assert result.final_score == 75
    assert "GV.RM-06" in result.explanation


def test_gv03_dos_facetas_no_alcanzan_el_100():
    evidence = [
        _claim(
            "risk_tolerance",
            {
                "objetivos_riesgo": "x",
                "tolerancia": "baja",
                "integracion_empresarial": True,
                "opciones_respuesta": True,
            },
        )
    ]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 75


def test_gv03_sin_tolerancia_es_50():
    evidence = [_claim("risk_tolerance", {"objetivos_riesgo": "x"})]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 50


def test_gv03_la_estrategia_se_lee_de_todos_los_fragmentos_del_documento():
    """Objetivos y tolerancia en un fragmento y las facetas en otro: antes puntuaba solo el
    fragmento mas confiable (75) y perdia el resto de GV.RM."""

    objetivos = _claim(
        "risk_tolerance", {"objetivos_riesgo": "x", "tolerancia": "baja"}, confianza=0.95
    )
    facetas = _claim(
        "risk_tolerance",
        {
            "integracion_empresarial": True,
            "opciones_respuesta": True,
            "metodo_estandarizado": True,
        },
        confianza=0.7,
    )

    result = gv03_risk_tolerance.evaluate([facetas, objetivos])

    assert result.final_score == 100
    assert set(result.evidence_ids) == {objetivos.id, facetas.id}


def test_gv03_generico_es_25():
    evidence = [_claim("risk_tolerance", {})]
    assert gv03_risk_tolerance.evaluate(evidence).final_score == 25


# --- CRI-ID-03 ---


def test_id03_proceso_con_registro_impactos_y_probabilidades_es_100():
    evidence = [
        _claim(
            "process_defined",
            {
                "proceso": "riesgos",
                "pasos": "x",
                "registro_riesgos": True,
                "impactos": True,
                "probabilidades": True,
            },
        )
    ]
    assert id03_risk_assessment.evaluate(evidence).final_score == 100


def test_id03_registro_sin_impactos_ni_probabilidades_es_75():
    """ID.RA-04 pide impactos y probabilidades registrados: un registro de riesgos sin ellos no
    llega al 100 por muy priorizado que este."""

    evidence = [
        _claim(
            "process_defined",
            {"proceso": "riesgos", "pasos": "x", "registro_riesgos": True, "priorizacion": True},
        )
    ]

    resultado = id03_risk_assessment.evaluate(evidence)

    assert resultado.final_score == 75
    assert "ID.RA-04" in resultado.explanation


def test_id03_registro_e_impactos_pueden_venir_en_otro_fragmento():
    """El registro y los impactos/probabilidades de ID.RA-04 pueden estar en un fragmento distinto
    del proceso: antes solo contaba el fragmento mas confiable (50)."""

    proceso = _claim("process_defined", {"proceso": "riesgos", "pasos": "x"}, confianza=0.95)
    registro = _claim(
        "process_defined",
        {"priorizacion": True, "impactos": True, "probabilidades": True},
        confianza=0.7,
    )

    result = id03_risk_assessment.evaluate([registro, proceso])

    assert result.final_score == 100
    assert set(result.evidence_ids) == {proceso.id, registro.id}


def test_id03_proceso_sin_registro_es_50():
    evidence = [_claim("process_defined", {"proceso": "riesgos", "pasos": "x"})]
    assert id03_risk_assessment.evaluate(evidence).final_score == 50


def test_id03_registro_impactos_y_probabilidades_sin_pasos_es_75():
    """El prompt pide `pasos` como texto libre y el modelo suele omitirlo: antes el proceso caia a
    25 ("descrita de forma generica") aunque sus facetas lo documentaran, y el escenario good
    bajaba de Tier 4 a Tier 1 (docs/09 §109)."""

    evidence = [
        _claim(
            "process_defined",
            {
                "proceso": "riesgos",
                "impactos": True,
                "priorizacion": True,
                "probabilidades": True,
                "registro_riesgos": True,
                "responsables": "CISO",
            },
        )
    ]

    resultado = id03_risk_assessment.evaluate(evidence)

    assert resultado.final_score == 75
    assert "sin pasos detallados" in resultado.explanation


def test_id03_proceso_de_riesgos_generico_es_25():
    evidence = [_claim("process_defined", {"proceso": "riesgos", "registro_riesgos": True})]
    assert id03_risk_assessment.evaluate(evidence).final_score == 25


def test_id03_no_toma_otro_proceso_por_traer_las_claves_en_null():
    """El prompt pide `registro_riesgos`/`priorizacion` en todo `process_defined`: un proceso de
    recuperacion los trae en null y antes contaba como proceso de riesgos (ID-03 = 75)."""

    evidence = [
        _claim(
            "process_defined",
            {
                "proceso": "recuperacion",
                "pasos": "x",
                "registro_riesgos": None,
                "priorizacion": False,
            },
        )
    ]
    result = id03_risk_assessment.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVIDENCIA_INSUFICIENTE, None)


def test_id03_solo_proceso_de_recuperacion_es_insuficiente():
    evidence = [_claim("process_defined", {"proceso": "recuperacion", "pasos": "x"})]
    result = id03_risk_assessment.evaluate(evidence)
    assert (result.estado, result.final_score) == (Estado.EVIDENCIA_INSUFICIENTE, None)


# --- CRI-ID-02 ---


def test_id02_criticidad_por_activo_es_100():
    evidence = [_claim("data_inventory", {"criticidad": [{"activo": "db", "nivel": "alta"}]})]
    assert id02_asset_criticality.evaluate(evidence).final_score == 100


def test_id02_criticidad_generica_es_50():
    evidence = [_claim("data_inventory", {"clasificacion": "alta"})]
    assert id02_asset_criticality.evaluate(evidence).final_score == 50


# --- CRI-ID-01 ---


def test_id01_cobertura_total_es_100():
    evidence = [
        _claim("data_inventory", {"activos": ["aws_db_instance", "aws_s3_bucket"]}),
        _tf_resource("aws_db_instance"),
        _tf_resource("aws_s3_bucket"),
    ]
    assert id01_asset_inventory.evaluate(evidence).final_score == 100


def test_id01_sin_tf_es_mencion_sin_cobertura():
    evidence = [_claim("data_inventory", {"activos": ["aws_db_instance"]})]
    assert id01_asset_inventory.evaluate(evidence).final_score == 25


# --- CRI-RC-01 ---


def test_rc01_procedimiento_completo_es_100():
    evidence = [
        _claim(
            "process_defined",
            {
                "proceso": "recuperacion",
                "pasos": "x",
                "criterios_activacion": "y",
                "responsables": "equipo",
            },
        )
    ]
    assert rc01_recovery_procedure.evaluate(evidence).final_score == 100


def test_rc01_los_criterios_de_activacion_pueden_venir_en_otro_fragmento():
    procedimiento = _claim(
        "process_defined",
        {"proceso": "recuperacion", "pasos": "x", "responsables": "equipo"},
        confianza=0.95,
    )
    activacion = _claim(
        "process_defined", {"proceso": "recuperacion", "criterios_activacion": "y"}, confianza=0.7
    )

    result = rc01_recovery_procedure.evaluate([activacion, procedimiento])

    assert result.final_score == 100
    assert set(result.evidence_ids) == {procedimiento.id, activacion.id}


def test_rc01_solo_backup_policy_es_50():
    evidence = [_claim("backup_policy", {"respaldo": True, "verificacion_integridad": True})]
    assert rc01_recovery_procedure.evaluate(evidence).final_score == 50


def test_rc01_sin_procedimiento_ni_backup_es_insuficiente():
    assert rc01_recovery_procedure.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


# --- CRI-DE-01 ---


def test_de01_centralizado_y_sistema_es_100():
    evidence = [_tf_logging(habilitado=True, multi_region=True), _syslog()]
    assert de01_monitoring.evaluate(evidence).final_score == 100


def test_de01_habilitado_sin_centralizar_es_75():
    evidence = [_tf_logging(habilitado=True)]
    assert de01_monitoring.evaluate(evidence).final_score == 75


def test_de01_el_bucket_del_trail_no_cuenta_como_centralizacion():
    """`destino` es obligatorio en `aws_cloudtrail`, asi que siempre viene: aceptarlo hacia que la
    condicion de centralizacion fuera siempre verdadera (docs/09 §64)."""

    trail = _tf_logging(habilitado=True, multi_region=False)
    con_destino = trail.model_copy(update={"value": {**trail.value, "destino": "org-logs"}})
    assert de01_monitoring.evaluate([con_destino, _syslog()]).final_score == 75


def test_de01_sin_configuracion_es_insuficiente():
    assert de01_monitoring.evaluate([]).estado == Estado.EVIDENCIA_INSUFICIENTE


# --- Contradicciones dentro de un documento (docs/09 §101) ------------------------------------


def test_gv02_a_document_that_denies_the_resources_in_another_fragment_does_not_get_them(
    methodology,
):
    completa = _claim(
        "role_assigned",
        {
            "roles": [
                {
                    "rol": "CISO",
                    "responsable": "Ana",
                    "responsabilidades": "programa",
                    "autoridad": "decision",
                }
            ],
            "recursos_asignados": False,
            "practicas_rh": True,
        },
        confianza=0.95,
    )
    niega = _claim("role_assigned", {"recursos_asignados": True}, confianza=0.6)

    (result,) = engine.evaluate_only(methodology, [niega, completa], ["CRI-GV-02"])

    assert result.final_score == 75
    assert "recursos asignados" in result.explanation
    assert "se contradice sobre recursos_asignados" in result.explanation


def test_gv02_the_same_resources_declared_in_another_document_do_count(methodology):
    completa = _claim(
        "role_assigned",
        {
            "roles": [
                {
                    "rol": "CISO",
                    "responsable": "Ana",
                    "responsabilidades": "programa",
                    "autoridad": "decision",
                }
            ],
            "recursos_asignados": False,
            "practicas_rh": True,
        },
        confianza=0.95,
    )
    otra = _claim("role_assigned", {"recursos_asignados": True}, confianza=0.6).model_copy(
        update={"subject_ref": "doc:otra-politica", "locator": Locator(file="otra.md")}
    )

    (result,) = engine.evaluate_only(methodology, [completa, otra], ["CRI-GV-02"])

    assert result.final_score == 100
    assert "se contradice" not in result.explanation


def test_gv03_a_fragment_that_denies_a_facet_leaves_the_strategy_in_75(methodology):
    estrategia = _claim(
        "risk_tolerance",
        {
            "objetivos_riesgo": "x",
            "tolerancia": "baja",
            "integracion_empresarial": False,
            "opciones_respuesta": True,
            "lineas_comunicacion": True,
        },
        confianza=0.95,
    )
    niega = _claim("risk_tolerance", {"integracion_empresarial": True}, confianza=0.6)

    (result,) = engine.evaluate_only(methodology, [niega, estrategia], ["CRI-GV-03"])

    assert result.final_score == 75
    assert "se contradice sobre integracion_empresarial" in result.explanation


def test_gv03_the_facet_declared_in_another_document_counts(methodology):
    estrategia = _claim(
        "risk_tolerance",
        {
            "objetivos_riesgo": "x",
            "tolerancia": "baja",
            "integracion_empresarial": False,
            "opciones_respuesta": True,
            "lineas_comunicacion": True,
        },
        confianza=0.95,
    )
    otra = _claim("risk_tolerance", {"integracion_empresarial": True}, confianza=0.6).model_copy(
        update={"subject_ref": "doc:otra-politica", "locator": Locator(file="otra.md")}
    )

    (result,) = engine.evaluate_only(methodology, [estrategia, otra], ["CRI-GV-03"])

    assert result.final_score == 100
    assert "se contradice" not in result.explanation


def test_id03_a_fragment_that_denies_the_impacts_leaves_the_process_in_75(methodology):
    proceso = _claim(
        "process_defined",
        {
            "proceso": "riesgos",
            "pasos": "x",
            "registro_riesgos": True,
            "impactos": False,
            "probabilidades": False,
        },
        confianza=0.95,
    )
    niega = _claim("process_defined", {"proceso": "riesgos", "impactos": True}, confianza=0.6)

    (result,) = engine.evaluate_only(methodology, [niega, proceso], ["CRI-ID-03"])

    assert result.final_score == 75
    assert "se contradice sobre impactos" in result.explanation


def test_id03_impacts_declared_in_another_document_do_count(methodology):
    proceso = _claim(
        "process_defined",
        {
            "proceso": "riesgos",
            "pasos": "x",
            "registro_riesgos": True,
            "impactos": False,
            "probabilidades": False,
        },
        confianza=0.95,
    )
    otra = _claim(
        "process_defined", {"proceso": "riesgos", "impactos": True}, confianza=0.6
    ).model_copy(update={"subject_ref": "doc:otra-politica", "locator": Locator(file="otra.md")})

    (result,) = engine.evaluate_only(methodology, [proceso, otra], ["CRI-ID-03"])

    assert result.final_score == 100
    assert "se contradice" not in result.explanation
