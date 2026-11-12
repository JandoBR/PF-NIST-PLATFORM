"""Normalizacion de cantidades escritas con palabras (docs/05 §2.3 E5, docs/09 §106)."""

import pytest

from app.ai.numbers import normalizar_cantidades, numero


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("noventa días", "90 días"),
        ("setenta y dos horas", "72 horas"),
        ("cada tres meses", "cada 3 meses"),
        ("dos semanas", "2 semanas"),
        ("un día", "1 día"),
        ("media hora", "0.5 hora"),
        ("treinta y cinco días", "35 días"),
        ("mil doscientos días", "1200 días"),
        ("dos mil veintiséis días", "2026 días"),
        ("se conservan durante noventa días.", "se conservan durante 90 días."),
        ("ninety days", "90 days"),
        ("seventy-two hours", "72 hours"),
        ("one hundred twenty days", "120 days"),
        ("a month", "1 month"),
    ],
)
def test_number_words_become_digits_before_a_unit(texto, esperado):
    assert normalizar_cantidades(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "no hay procedimiento documentado",
        "uno de los roles",
        "el jefe de TI asume las funciones",
        "",
    ],
)
def test_text_without_a_quantity_and_unit_is_left_untouched(texto):
    assert normalizar_cantidades(texto) == texto


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("noventa", 90),
        ("setenta y dos", 72),
        ("dos mil veintiséis", 2026),
        ("mil doscientos", 1200),
        ("un millón", 1_000_000),
        ("half", 0.5),
        ("no es un numero", None),
    ],
)
def test_numero_parses_cardinals(texto, esperado):
    assert numero(texto) == esperado
