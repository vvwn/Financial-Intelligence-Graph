"""Extractors: turn raw documents into structured facts.

Only `annual_report` is implemented today (subsidiary table). Financial
statement parsing and customer/supplier extraction are Phase 2 work.
"""

from app.extractors.annual_report import (
    SubsidiaryExtraction,
    SubsidiaryRow,
    extract_subsidiaries,
)
from app.extractors.pdf import extract_text

__all__ = ["SubsidiaryExtraction", "SubsidiaryRow", "extract_subsidiaries", "extract_text"]
