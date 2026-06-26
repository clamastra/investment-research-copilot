"""
tests/test_sourcing.py — Tests for the EDGAR sourcing integration.

Covers:
  - Valid ticker/fund name returns structured filing results
  - Invalid query returns empty list (not a crash)
  - Each supported filing type can be searched
  - Unsupported filing type doesn't break the UI (FORM_TYPES coverage)
  - get_filing_pdfs: returns docs on success
  - get_filing_pdfs: returns error dict on network failure
  - get_filing_pdfs: returns error dict on malformed response
  - download_pdf: saves file to disk on success
  - download_pdf: returns error dict on network failure
  - Rate limit / network failure handled gracefully
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

import sourcing


# ---------------------------------------------------------------------------
# EDGAR search response builders
# ---------------------------------------------------------------------------

def _edgar_hit(entity="VANGUARD 500 INDEX FUND  (CIK 0000036405)",
               form="N-CSR",
               adsh="0000932471-24-023456",
               cik="0000036405",
               file_date="2024-11-27",
               period_ending="2024-09-30"):
    return {
        "_source": {
            "display_names": [entity],
            "form": form,
            "adsh": adsh,
            "ciks": [cik],
            "file_date": file_date,
            "period_ending": period_ending,
        }
    }


def _edgar_response(hits):
    return MagicMock(
        status_code=200,
        json=MagicMock(return_value={"hits": {"hits": hits}}),
    )


# ---------------------------------------------------------------------------
# search_edgar
# ---------------------------------------------------------------------------

class TestSearchEdgar:
    def test_valid_query_returns_list(self):
        resp = _edgar_response([_edgar_hit()])
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("Vanguard 500", ["N-CSR"])
        assert isinstance(results, list)
        assert len(results) == 1

    def test_result_contains_expected_keys(self):
        resp = _edgar_response([_edgar_hit()])
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("Vanguard 500", ["N-CSR"])
        r = results[0]
        assert "entity" in r
        assert "form_type" in r
        assert "date" in r
        assert "period" in r
        assert "accession" in r
        assert "cik" in r
        assert "description" in r

    def test_cik_suffix_stripped_from_entity_name(self):
        resp = _edgar_response([_edgar_hit(entity="PIMCO INCOME FUND  (CIK 0001234567)")])
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("PIMCO Income", ["N-CSR"])
        assert "CIK" not in results[0]["entity"]
        assert "0001234567" not in results[0]["entity"]

    def test_empty_hits_returns_empty_list(self):
        resp = _edgar_response([])
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("nonexistent fund xyz", ["N-CSR"])
        assert results == []

    def test_network_failure_returns_error_dict(self):
        with patch("sourcing.requests.get", side_effect=requests.RequestException("timeout")):
            results = sourcing.search_edgar("any", ["N-CSR"])
        assert isinstance(results, dict)
        assert "error" in results

    def test_http_500_returns_error_dict(self):
        resp = MagicMock(status_code=500)
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("any", ["N-CSR"])
        assert isinstance(results, dict)
        assert "error" in results

    def test_results_sorted_most_recent_first(self):
        hits = [
            _edgar_hit(file_date="2023-01-15"),
            _edgar_hit(file_date="2024-11-27"),
            _edgar_hit(file_date="2022-06-01"),
        ]
        resp = _edgar_response(hits)
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("fund", ["N-CSR"])
        dates = [r["date"] for r in results]
        assert dates == sorted(dates, reverse=True)

    def test_max_results_respected(self):
        hits = [_edgar_hit() for _ in range(15)]
        resp = _edgar_response(hits)
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("fund", ["N-CSR"], max_results=5)
        assert len(results) <= 5

    @pytest.mark.parametrize("form_type", list(sourcing.FORM_TYPES.keys()))
    def test_each_supported_form_type(self, form_type):
        resp = _edgar_response([_edgar_hit(form=form_type)])
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("any", [form_type])
        assert isinstance(results, list)

    def test_period_null_becomes_na(self):
        hit = _edgar_hit()
        hit["_source"]["period_ending"] = None
        resp = _edgar_response([hit])
        with patch("sourcing.requests.get", return_value=resp):
            results = sourcing.search_edgar("fund", ["N-CSR"])
        assert results[0]["period"] == "N/A"


# ---------------------------------------------------------------------------
# get_filing_pdfs
# ---------------------------------------------------------------------------

def _index_response(items):
    return MagicMock(
        status_code=200,
        json=MagicMock(return_value={"directory": {"item": items}}),
    )


class TestGetFilingPdfs:
    def test_returns_pdf_docs(self):
        items = [{"name": "report.pdf", "size": "204800"}]
        resp = _index_response(items)
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert len(docs) == 1
        assert docs[0]["doc_type"] == "PDF"
        assert docs[0]["name"] == "report.pdf"

    def test_returns_html_docs(self):
        items = [{"name": "filing.htm", "size": "512000"}]
        resp = _index_response(items)
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert len(docs) == 1
        assert docs[0]["doc_type"] == "HTML"

    def test_skips_index_and_header_files(self):
        items = [
            {"name": "0000932471-24-023456-index.htm", "size": "1024"},
            {"name": "report.htm", "size": "512000"},
        ]
        resp = _index_response(items)
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        names = [d["name"] for d in docs]
        assert "0000932471-24-023456-index.htm" not in names
        assert "report.htm" in names

    def test_network_failure_returns_error_dict(self):
        with patch("sourcing.requests.get", side_effect=requests.RequestException("timeout")):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert len(docs) == 1
        assert "error" in docs[0]

    def test_malformed_json_returns_error_dict(self):
        resp = MagicMock(status_code=200)
        resp.json.side_effect = ValueError("bad json")
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert len(docs) == 1
        assert "error" in docs[0]

    def test_http_error_returns_error_dict(self):
        resp = MagicMock(status_code=404)
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert len(docs) == 1
        assert "error" in docs[0]

    def test_pdfs_sorted_before_html(self):
        items = [
            {"name": "filing.htm", "size": "512000"},
            {"name": "exhibit.pdf", "size": "102400"},
        ]
        resp = _index_response(items)
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert docs[0]["doc_type"] == "PDF"

    def test_size_parsed_correctly(self):
        items = [{"name": "report.pdf", "size": "1048576"}]
        resp = _index_response(items)
        with patch("sourcing.requests.get", return_value=resp):
            docs = sourcing.get_filing_pdfs("36405", "0000932471-24-023456")
        assert docs[0]["size_kb"] == 1024.0


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------

class TestDownloadPdf:
    def test_saves_file_to_raw_pdf_dir(self, tmp_pdf_dir):
        resp = MagicMock(status_code=200)
        resp.iter_content.return_value = [b"PDF content bytes"]
        resp.raise_for_status.return_value = None
        with patch("sourcing.requests.get", return_value=resp), \
             patch("sourcing.RAW_PDF_DIR", tmp_pdf_dir):
            result = sourcing.download_pdf("https://example.com/file.pdf", "file.pdf")
        assert result["success"] is True
        assert (tmp_pdf_dir / "file.pdf").exists()

    def test_returns_error_dict_on_network_failure(self, tmp_pdf_dir):
        with patch("sourcing.requests.get", side_effect=requests.RequestException("timeout")), \
             patch("sourcing.RAW_PDF_DIR", tmp_pdf_dir):
            result = sourcing.download_pdf("https://example.com/file.pdf", "file.pdf")
        assert result["success"] is False
        assert "error" in result

    def test_returns_error_dict_on_http_error(self, tmp_pdf_dir):
        resp = MagicMock(status_code=404)
        resp.raise_for_status.side_effect = requests.HTTPError("Not Found")
        with patch("sourcing.requests.get", return_value=resp), \
             patch("sourcing.RAW_PDF_DIR", tmp_pdf_dir):
            result = sourcing.download_pdf("https://example.com/missing.pdf", "missing.pdf")
        assert result["success"] is False

    def test_html_file_download_works(self, tmp_pdf_dir):
        resp = MagicMock(status_code=200)
        resp.iter_content.return_value = [b"<html>filing</html>"]
        resp.raise_for_status.return_value = None
        with patch("sourcing.requests.get", return_value=resp), \
             patch("sourcing.RAW_PDF_DIR", tmp_pdf_dir):
            result = sourcing.download_pdf("https://example.com/filing.htm", "filing.htm")
        assert result["success"] is True
        assert (tmp_pdf_dir / "filing.htm").exists()
