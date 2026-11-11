from pathlib import Path

from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.adapters.documents.extraction_text import (
    DEFAULT_MAX_CHARS_PER_CHUNK,
    chunk_markdown,
    chunk_pdf,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "documents"


def _sections(chunk):
    return [segmento.locator.section for segmento in chunk.segmentos]


def test_markdown_groups_small_sections_into_one_chunk():
    chunks = chunk_markdown(FIXTURES / "politica-seguridad.md")

    assert len(chunks) == 1
    assert _sections(chunks[0]) == [
        "Politica de Seguridad de la Informacion",
        "Revision",
    ]
    assert "Direccion General" in chunks[0].text
    assert "anual" in chunks[0].text
    assert chunks[0].locator.section == "Politica de Seguridad de la Informacion"
    # El texto agrupado conserva los encabezados: el modelo ve la estructura.
    assert "# Politica de Seguridad de la Informacion" in chunks[0].text
    assert "## Revision" in chunks[0].text


def test_markdown_without_headings_is_one_chunk(tmp_path):
    doc = tmp_path / "sin-encabezados.md"
    doc.write_text("Texto plano sin encabezados de ningun tipo.")

    chunks = chunk_markdown(doc)

    assert len(chunks) == 1
    assert chunks[0].locator.section is None
    assert chunks[0].segmentos[0].locator.section is None


def test_markdown_budget_splits_without_cutting_a_section(tmp_path):
    doc = tmp_path / "muchas.md"
    doc.write_text("# Uno\n" + "a" * 40 + "\n# Dos\n" + "b" * 40 + "\n# Tres\n" + "c" * 40 + "\n")

    chunks = chunk_markdown(doc, max_chars=100)

    assert [_sections(chunk) for chunk in chunks] == [["Uno", "Dos"], ["Tres"]]
    for chunk in chunks:
        assert len(chunk.text) <= 100
        assert chunk.text.count("# ") == len(chunk.segmentos)


def test_an_oversized_section_stays_alone_in_its_chunk(tmp_path):
    doc = tmp_path / "grande.md"
    doc.write_text(
        "# Corta\ntexto\n# Enorme\n" + "x" * (DEFAULT_MAX_CHARS_PER_CHUNK + 100) + "\n# Otra\nfin\n"
    )

    chunks = chunk_markdown(doc)

    assert [_sections(chunk) for chunk in chunks] == [["Corta"], ["Enorme"], ["Otra"]]
    assert len(chunks[1].text) > DEFAULT_MAX_CHARS_PER_CHUNK


def test_markdown_ignores_headings_inside_fenced_code(tmp_path):
    doc = tmp_path / "con-codigo.md"
    doc.write_text(
        "# Politica\n\n```bash\n# esto es un comentario\necho hola\n```\n\n# Revision\ntexto\n"
    )

    chunks = chunk_markdown(doc)

    assert [_sections(chunk) for chunk in chunks] == [["Politica", "Revision"]]
    assert "esto es un comentario" in chunks[0].text[: chunks[0].segmentos[0].fin]


def _pdf_with_pages(path: Path, texts: list[str]) -> Path:
    pdf = canvas.Canvas(str(path))
    for text in texts:
        pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return path


def test_pdf_pages_are_grouped_and_keep_their_page(tmp_path):
    pdf = _pdf_with_pages(tmp_path / "paginas.pdf", ["pagina uno", "pagina dos"])

    chunks = chunk_pdf(pdf)

    assert len(chunks) == 1
    assert [segmento.locator.page for segmento in chunks[0].segmentos] == [1, 2]
    assert "pagina uno" in chunks[0].text and "pagina dos" in chunks[0].text


def test_pdf_budget_keeps_one_page_per_chunk(tmp_path):
    pdf = _pdf_with_pages(tmp_path / "separadas.pdf", ["pagina uno", "pagina dos"])

    chunks = chunk_pdf(pdf, max_chars=10)

    assert [[segmento.locator.page for segmento in chunk.segmentos] for chunk in chunks] == [
        [1],
        [2],
    ]


def test_encrypted_pdf_is_skipped_instead_of_crashing(tmp_path):
    pdf = tmp_path / "protegido.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secreto")
    with pdf.open("wb") as fh:
        writer.write(fh)

    assert chunk_pdf(pdf) == []
