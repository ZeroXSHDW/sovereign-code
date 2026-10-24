from __future__ import annotations

from pathlib import Path

from sovereign_code import pdf


def _text_pdf(path: Path, text: str = "Hello PDF World") -> Path:
    pdf_content = (
        "%PDF-1.4\n"
        "1 0 obj\n"
        "<< /Type /Catalog /Pages 2 0 R >>\n"
        "endobj\n"
        "2 0 obj\n"
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        "endobj\n"
        "3 0 obj\n"
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        "   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
        "endobj\n"
        "4 0 obj\n"
        "<< /Length 60 >>\n"
        "stream\n"
        "BT\n"
        "/F1 12 Tf\n"
        "100 700 Td\n"
        f"({text}) Tj\n"
        "ET\n"
        "endstream\n"
        "endobj\n"
        "5 0 obj\n"
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        "endobj\n"
        "xref\n"
        "0 6\n"
        "0000000000 65535 f \n"
        "0000000009 0000000058 f \n"
        "0000000058 0000000115 f \n"
        "0000000115 0000000244 f \n"
        "0000000244 0000000338 f \n"
        "0000000338 0000000397 f \n"
        "trailer\n"
        "<< /Size 6 /Root 1 0 R >>\n"
        "startxref\n"
        "466\n"
        "%%EOF\n"
    )
    path.write_text(pdf_content, encoding="utf-8")
    return path


def test_is_valid_pdf(tmp_path: Path) -> None:
    p = _text_pdf(tmp_path / "a.pdf")
    assert pdf.is_valid_pdf(p) is True
    assert pdf.is_valid_pdf(tmp_path / "nope.txt") is False


def test_extract_text_from_pdf(tmp_path: Path) -> None:
    p = _text_pdf(tmp_path / "a.pdf", "Hello PDF World")
    text = pdf.extract_text_from_pdf(p)
    assert "Hello" in text


def test_extract_tables_returns_list(tmp_path: Path) -> None:
    p = _text_pdf(tmp_path / "a.pdf", "Hello PDF World")
    tables = pdf.extract_tables(p)
    assert isinstance(tables, list)


def test_extract_figures_returns_list(tmp_path: Path) -> None:
    p = _text_pdf(tmp_path / "a.pdf")
    figures = pdf.extract_figures(p, dpi=100)
    assert isinstance(figures, list)
    assert len(figures) == 1


def test_pdf_reader_error() -> None:
    assert issubclass(pdf.PDFExtractError, pdf.PDFReaderError)
