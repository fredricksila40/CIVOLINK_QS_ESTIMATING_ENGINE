"""Branded corporate document generators (Phase 15).

Presentation sinks only: BOQ/rate DTOs plus company-profile metadata in,
formatted .docx files in output/ out. No calculation, no core contact.
"""

from .document_base import BaseBrandedDocument
from .invoice_word import build_invoice_document
from .quotation_word import build_quotation_document

__all__ = [
    "BaseBrandedDocument",
    "build_quotation_document",
    "build_invoice_document",
]
