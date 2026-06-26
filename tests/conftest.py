"""
tests/conftest.py — Shared fixtures for CapitalContext test suite.

Run all tests from the project root:
    pytest tests/

Individual test files:
    pytest tests/test_ingest.py
    pytest tests/test_rag.py
    pytest tests/test_sourcing.py
    pytest tests/test_outputs.py
    pytest tests/test_edge_cases.py
"""

import io
import json
import os
import sys
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the project root is on sys.path so all modules import correctly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures: temp directories
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_pdf_dir(tmp_path):
    """Temporary directory standing in for data/raw_pdfs/."""
    d = tmp_path / "raw_pdfs"
    d.mkdir()
    return d


@pytest.fixture
def tmp_vector_dir(tmp_path):
    """Temporary ChromaDB vector store directory."""
    d = tmp_path / "vector_store"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Fixtures: minimal valid PDF bytes (uses PyMuPDF to create in-memory PDF)
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_pdf_path(tmp_pdf_dir):
    """Creates a minimal single-page PDF with known text content."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Vanguard 500 Index Fund Annual Report 2024.\n"
                                "This fund tracks the S&P 500 index. "
                                "Management fees are 0.03%. "
                                "Total assets under management are $500B.")
    pdf_bytes = doc.tobytes()
    doc.close()

    p = tmp_pdf_dir / "vanguard_500_annual_report.pdf"
    p.write_bytes(pdf_bytes)
    return p


@pytest.fixture
def multi_page_pdf_path(tmp_pdf_dir):
    """Creates a 3-page PDF to test page-level chunking and metadata."""
    import fitz
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text(
            (72, 72),
            f"Page {i + 1} content. "
            f"BlackRock Total Return Fund quarterly report. "
            f"Fixed income strategy targeting investment-grade bonds. " * 10,
        )
    pdf_bytes = doc.tobytes()
    doc.close()

    p = tmp_pdf_dir / "blackrock_total_return.pdf"
    p.write_bytes(pdf_bytes)
    return p


@pytest.fixture
def corrupt_pdf_path(tmp_pdf_dir):
    """A file with .pdf extension but not valid PDF content."""
    p = tmp_pdf_dir / "corrupt.pdf"
    p.write_bytes(b"this is not a valid PDF file at all \x00\x01\x02")
    return p


@pytest.fixture
def blank_pdf_path(tmp_pdf_dir):
    """A real PDF with only blank pages (no extractable text)."""
    import fitz
    doc = fitz.open()
    doc.new_page()   # blank — no text inserted
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()

    p = tmp_pdf_dir / "blank.pdf"
    p.write_bytes(pdf_bytes)
    return p


# ---------------------------------------------------------------------------
# Fixtures: HTML content (iXBRL-style SEC filing)
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_html_path(tmp_pdf_dir):
    """Minimal HTML filing with some iXBRL namespace noise to strip."""
    html = textwrap.dedent("""\
        <html>
        <head><title>N-CSR Filing</title></head>
        <body>
          <ix:header>XBRL header noise 0000036405 http://xbrl.sec.gov/dei/2023</ix:header>
          <p>PIMCO Income Fund Semi-Annual Report</p>
          <p>The fund invests primarily in high-quality fixed income instruments.</p>
          <p>Total net assets: $150 billion. Distribution yield: 7.2%.</p>
          <div>Management fee: 0.55% annually.</div>
          <ix:nonNumeric name="dei:DocumentType">N-CSR</ix:nonNumeric>
        </body>
        </html>
    """)
    p = tmp_pdf_dir / "pimco_income_ncsr.htm"
    p.write_text(html, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixtures: mocked ChromaDB collection
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_collection():
    """A MagicMock standing in for a ChromaDB collection with 5 chunks."""
    col = MagicMock()
    col.count.return_value = 5
    col.query.return_value = {
        "documents": [[
            "Vanguard 500 tracks the S&P 500 with a 0.03% expense ratio.",
            "The fund returned 26% in 2023, in line with the benchmark.",
            "Risk factors include market concentration in mega-cap tech stocks.",
        ]],
        "metadatas": [[
            {"source": "vanguard_500_annual_report", "page": 1, "file": "vanguard_500_annual_report.pdf", "asset_class": "US Equity"},
            {"source": "vanguard_500_annual_report", "page": 2, "file": "vanguard_500_annual_report.pdf", "asset_class": "US Equity"},
            {"source": "vanguard_500_annual_report", "page": 3, "file": "vanguard_500_annual_report.pdf", "asset_class": "US Equity"},
        ]],
        "distances": [[0.15, 0.25, 0.45]],
    }
    return col


@pytest.fixture
def empty_mock_collection():
    """ChromaDB collection with zero documents."""
    col = MagicMock()
    col.count.return_value = 0
    return col


# ---------------------------------------------------------------------------
# Fixtures: environment
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_test_api_key(monkeypatch):
    """Ensures ANTHROPIC_API_KEY is set for all tests that might check it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-placeholder")
