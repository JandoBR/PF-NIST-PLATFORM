from pathlib import Path

from pypdf import PdfWriter

from app.adapters.documents.extraction_text import chunk_markdown, chunk_pdf

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


def test_markdown_ignores_headings_inside_fenced_code(tmp_path):
    doc = tmp_path / "con-codigo.md"
    doc.write_text(
        "# Politica\n\n```bash\n# esto es un comentario\necho hola\n```\n\n# Revision\ntexto\n"
    )

    chunks = chunk_markdown(doc)

    assert [c.locator.section for c in chunks] == ["Politica", "Revision"]
    assert "esto es un comentario" in chunks[0].text


def test_markdown_bom_keeps_the_first_heading(tmp_path):
    doc = tmp_path / "con-bom.md"
    doc.write_text("\ufeff# Politica\ntexto\n", encoding="utf-8")

    chunks = chunk_markdown(doc)

    assert chunks[0].locator.section == "Politica"


def test_encrypted_pdf_is_skipped_instead_of_crashing(tmp_path):
    pdf = tmp_path / "protegido.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secreto")
    with pdf.open("wb") as fh:
        writer.write(fh)

    assert chunk_pdf(pdf) == []
