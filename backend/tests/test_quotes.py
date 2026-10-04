from app.ai.quotes import quote_in_text

TEXTO = "## Politica\n\n- **La organizacion** revisa la politica cada año, según el CISO.\n"


def test_cita_exacta():
    assert quote_in_text("revisa la politica cada año", TEXTO)


def test_ignora_markdown_vinetas_acentos_y_puntuacion():
    assert quote_in_text("La organización revisa la política cada ano segun el CISO", TEXTO)
    assert quote_in_text("“la organizacion”  revisa — la politica", TEXTO)


def test_palabras_inventadas_o_en_otro_orden_fallan():
    assert not quote_in_text("revisa la politica cada mes", TEXTO)
    assert not quote_in_text("politica la revisa", TEXTO)


def test_cita_vacia_o_solo_puntuacion_falla():
    assert not quote_in_text("", TEXTO)
    assert not quote_in_text("**-- ..", TEXTO)
