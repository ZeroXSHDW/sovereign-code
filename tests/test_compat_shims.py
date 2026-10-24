"""Compatibility re-export shims that alias the pdf module under old names."""

from __future__ import annotations

import importlib


def test_compat_shims_reexport_pdf() -> None:
    """Each legacy module name still resolves and re-exports pdf symbols."""
    for name in ("doc_ocr", "document", "documents", "ocr", "pdf_ocr", "pdf_reader", "pdf_tools"):
        module = importlib.import_module(f"sovereign_code.{name}")
        assert hasattr(module, "extract_pdf_text")  # a representative pdf export
