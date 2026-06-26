"""
tests/test_ingest.py — Tests for the PDF/HTML ingestion pipeline.

Covers:
  - PDF text extraction (valid, corrupt, blank)
  - HTML text extraction and iXBRL namespace stripping
  - Chunking correctness
  - Metadata completeness on every chunk
  - ChromaDB add operations
  - Per-file error isolation in ingest_all()
  - Classification fallback behaviour
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

import ingest as ing


# ---------------------------------------------------------------------------
# extract_pages — PDF text extraction
# ---------------------------------------------------------------------------

class TestExtractPages:
    def test_valid_pdf_returns_pages(self, simple_pdf_path):
        pages = ing.extract_pages(simple_pdf_path)
        assert len(pages) >= 1
        assert all("page_num" in p and "text" in p for p in pages)

    def test_valid_pdf_text_nonempty(self, simple_pdf_path):
        pages = ing.extract_pages(simple_pdf_path)
        assert all(len(p["text"]) > 0 for p in pages)

    def test_page_numbers_start_at_one(self, simple_pdf_path):
        pages = ing.extract_pages(simple_pdf_path)
        assert pages[0]["page_num"] == 1

    def test_multi_page_pdf_page_count(self, multi_page_pdf_path):
        pages = ing.extract_pages(multi_page_pdf_path)
        assert len(pages) == 3

    def test_corrupt_pdf_returns_empty_list(self, corrupt_pdf_path):
        pages = ing.extract_pages(corrupt_pdf_path)
        assert pages == []

    def test_blank_pdf_returns_empty_list(self, blank_pdf_path):
        pages = ing.extract_pages(blank_pdf_path)
        assert pages == []


# ---------------------------------------------------------------------------
# extract_html_pages — HTML text extraction
# ---------------------------------------------------------------------------

class TestExtractHtmlPages:
    def test_html_returns_pages(self, simple_html_path):
        pages = ing.extract_html_pages(simple_html_path)
        assert len(pages) >= 1

    def test_html_strips_ixbrl_noise(self, simple_html_path):
        pages = ing.extract_html_pages(simple_html_path)
        full_text = " ".join(p["text"] for p in pages)
        # iXBRL boilerplate tags should not appear as text content
        assert "http://xbrl.sec.gov" not in full_text
        assert "ix:header" not in full_text

    def test_html_captures_meaningful_text(self, simple_html_path):
        pages = ing.extract_html_pages(simple_html_path)
        full_text = " ".join(p["text"] for p in pages)
        assert "PIMCO Income Fund" in full_text
        assert "fixed income" in full_text.lower()

    def test_html_page_numbers_sequential(self, simple_html_path):
        pages = ing.extract_html_pages(simple_html_path)
        nums = [p["page_num"] for p in pages]
        assert nums == list(range(1, len(pages) + 1))

    def test_empty_html_returns_empty_list(self, tmp_pdf_dir):
        p = tmp_pdf_dir / "empty.htm"
        p.write_text("<html><body></body></html>", encoding="utf-8")
        pages = ing.extract_html_pages(p)
        assert pages == []


# ---------------------------------------------------------------------------
# chunk_text — chunking
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "hello world"
        chunks = ing.chunk_text(text, chunk_size=1500, overlap=150)
        assert len(chunks) == 1
        assert chunks[0] == "hello world"

    def test_chunk_size_respected(self):
        text = "a" * 3000
        chunks = ing.chunk_text(text, chunk_size=1500, overlap=150)
        for chunk in chunks:
            assert len(chunk) <= 1500

    def test_overlap_produces_repeated_content(self):
        text = "a" * 1500 + "b" * 1500
        chunks = ing.chunk_text(text, chunk_size=1500, overlap=150)
        assert len(chunks) >= 2
        # The start of chunk 2 should overlap with the end of chunk 1
        assert chunks[1][:150] == chunks[0][-150:]

    def test_empty_text_returns_empty_list(self):
        chunks = ing.chunk_text("", chunk_size=1500, overlap=150)
        assert chunks == []

    def test_whitespace_only_text_returns_empty(self):
        chunks = ing.chunk_text("   \n\t  ", chunk_size=1500, overlap=150)
        assert chunks == []


# ---------------------------------------------------------------------------
# ingest_pdf — metadata completeness
# ---------------------------------------------------------------------------

class TestIngestPdf:
    def test_metadata_fields_on_every_chunk(self, simple_pdf_path, tmp_vector_dir):
        collection = MagicMock()
        added_metadatas = []

        def capture_add(documents, metadatas, ids):
            added_metadatas.extend(metadatas)

        collection.add.side_effect = capture_add

        with patch("ingest.VECTOR_STORE_DIR", tmp_vector_dir), \
             patch("ingest.classify_document", return_value="US Equity"):
            ing.ingest_pdf(simple_pdf_path, collection)

        assert len(added_metadatas) > 0
        for meta in added_metadatas:
            assert "source" in meta
            assert "page" in meta
            assert "file" in meta
            assert "asset_class" in meta

    def test_asset_class_stored_on_chunks(self, simple_pdf_path, tmp_vector_dir):
        collection = MagicMock()
        added_metadatas = []
        collection.add.side_effect = lambda documents, metadatas, ids: added_metadatas.extend(metadatas)

        with patch("ingest.classify_document", return_value="Fixed Income"):
            ing.ingest_pdf(simple_pdf_path, collection)

        assert all(m["asset_class"] == "Fixed Income" for m in added_metadatas)

    def test_corrupt_pdf_returns_zero_chunks(self, corrupt_pdf_path):
        collection = MagicMock()
        result = ing.ingest_pdf(corrupt_pdf_path, collection)
        assert result["chunks"] == 0
        collection.add.assert_not_called()

    def test_blank_pdf_returns_zero_chunks(self, blank_pdf_path):
        collection = MagicMock()
        result = ing.ingest_pdf(blank_pdf_path, collection)
        assert result["chunks"] == 0

    def test_chunk_ids_unique(self, simple_pdf_path):
        collection = MagicMock()
        all_ids = []
        collection.add.side_effect = lambda documents, metadatas, ids: all_ids.extend(ids)

        with patch("ingest.classify_document", return_value="US Equity"):
            ing.ingest_pdf(simple_pdf_path, collection)

        assert len(all_ids) == len(set(all_ids)), "Chunk IDs must be unique"


# ---------------------------------------------------------------------------
# ingest_all — per-file isolation
# ---------------------------------------------------------------------------

class TestIngestAll:
    def test_bad_file_does_not_abort_good_files(self, tmp_pdf_dir, tmp_vector_dir):
        # Write one good and one corrupt PDF
        import fitz
        good = tmp_pdf_dir / "good.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Good PDF content for testing.")
        good.write_bytes(doc.tobytes())
        doc.close()

        bad = tmp_pdf_dir / "bad.pdf"
        bad.write_bytes(b"not a pdf")

        with patch("ingest.RAW_PDF_DIR", tmp_pdf_dir), \
             patch("ingest.VECTOR_STORE_DIR", tmp_vector_dir), \
             patch("ingest.classify_document", return_value="Other"):
            summary = ing.ingest_all(clear_first=False)

        assert "good.pdf" in summary["results"]
        assert "bad.pdf" in summary["results"]
        # good.pdf should have chunks; bad.pdf should have 0
        assert summary["results"]["good.pdf"]["chunks"] > 0
        assert summary["results"]["bad.pdf"]["chunks"] == 0

    def test_empty_directory_returns_error(self, tmp_pdf_dir, tmp_vector_dir):
        with patch("ingest.RAW_PDF_DIR", tmp_pdf_dir), \
             patch("ingest.VECTOR_STORE_DIR", tmp_vector_dir):
            summary = ing.ingest_all(clear_first=False)
        assert "error" in summary

    def test_summary_includes_all_files(self, tmp_pdf_dir, tmp_vector_dir):
        import fitz
        for name in ["a.pdf", "b.pdf"]:
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), f"Content of {name}.")
            (tmp_pdf_dir / name).write_bytes(doc.tobytes())
            doc.close()

        with patch("ingest.RAW_PDF_DIR", tmp_pdf_dir), \
             patch("ingest.VECTOR_STORE_DIR", tmp_vector_dir), \
             patch("ingest.classify_document", return_value="Other"):
            summary = ing.ingest_all(clear_first=False)

        assert "a.pdf" in summary["results"]
        assert "b.pdf" in summary["results"]


# ---------------------------------------------------------------------------
# classify_document — fallback behaviour
# ---------------------------------------------------------------------------

class TestClassifyDocument:
    def test_valid_label_returned(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="US Equity")]
        with patch("ingest._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_response
            result = ing.classify_document("S&P 500 fund annual report", "vanguard_500")
        assert result == "US Equity"

    def test_unexpected_label_falls_back_to_other(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Cryptocurrency")]
        with patch("ingest._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = mock_response
            result = ing.classify_document("some text", "unknown_doc")
        assert result == "Other"

    def test_api_failure_falls_back_to_other(self):
        with patch("ingest._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.side_effect = Exception("API error")
            result = ing.classify_document("some text", "doc")
        assert result == "Other"

    def test_missing_api_key_falls_back_to_other(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Reset the cached client so it re-reads the env var
        ing._anthropic_client = None
        result = ing.classify_document("some text", "doc")
        assert result == "Other"
        ing._anthropic_client = None  # clean up
