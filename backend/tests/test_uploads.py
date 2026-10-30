import pytest

from app.core.uploads import safe_filename


def test_plain_name_is_kept():
    assert safe_filename("main.tf", tipo="terraform") == "main.tf"


def test_path_traversal_is_stripped_to_basename():
    assert safe_filename("../../etc/evil.tf", tipo="terraform") == "evil.tf"
    assert safe_filename("/etc/passwd.tf", tipo="terraform") == "passwd.tf"


def test_windows_separator_is_rejected():
    with pytest.raises(ValueError):
        safe_filename("..\\..\\evil.tf", tipo="terraform")


@pytest.mark.parametrize(
    "name", ["..\\..\\evil.tf", "a\\b.tf", "C:\\Windows\\evil.tf", "sub\\main.tf"]
)
def test_backslash_is_rejected_on_every_platform(name):
    """El saneo no puede depender del sistema operativo.

    `Path(name).name` trata `\\` como separador en Windows y como un caracter normal en Linux, asi
    que comprobarlo despues de normalizar hacia que en Windows `..\\..\\evil.tf` se aceptara como
    `evil.tf` y en Linux se rechazara. Se comprueba sobre el nombre original.
    """

    with pytest.raises(ValueError):
        safe_filename(name, tipo="terraform")


def test_extension_whitelist_per_type():
    assert safe_filename("config.yml", tipo="ansible") == "config.yml"
    assert safe_filename("events.jsonl", tipo="events") == "events.jsonl"
    with pytest.raises(ValueError):
        safe_filename("evil.exe", tipo="terraform")
    with pytest.raises(ValueError):
        safe_filename("sin_extension", tipo="terraform")
    with pytest.raises(ValueError):
        safe_filename("main.tf", tipo="documents")


@pytest.mark.parametrize("name", ["", "   ", None, ".", "..", "a\x00.tf"])
def test_empty_or_invalid_names_are_rejected(name):
    with pytest.raises(ValueError):
        safe_filename(name, tipo="terraform")


def test_overlong_name_is_rejected():
    with pytest.raises(ValueError, match="demasiado largo"):
        safe_filename("a" * 300 + ".md", tipo="documents")
