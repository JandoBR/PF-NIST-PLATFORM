from pathlib import Path

from app.adapters.documents.extraction_text import chunk_markdown

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents"


def test_markdown_splits_into_one_chunk_per_heading():
    chunks = chunk_markdown(FIXTURES / "politica-seguridad.md")

    assert [c.locator.section for c in chunks] == [
        "Politica de Seguridad de la Informacion",
        "Revision",
    ]
    assert "Direccion General" in chunks[0].text
    assert "anual" in chunks[1].text


def test_markdown_without_headings_is_one_chunk(tmp_path):
    doc = tmp_path / "sin-encabezados.md"
    doc.write_text("Texto plano sin encabezados de ningun tipo.")

    chunks = chunk_markdown(doc)

    assert len(chunks) == 1
    assert chunks[0].locator.section is None
