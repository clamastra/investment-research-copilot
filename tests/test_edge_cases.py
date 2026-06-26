"""
tests/test_edge_cases.py — Edge case and boundary condition tests.

Covers:
  - ChromaDB empty: all pipelines handle gracefully
  - Query too long: handled without crash
  - API key missing: clear error returned
  - API call failure: no silent crash
  - Collection stats on empty store
  - get_collection singleton: model loaded only once
  - clear_collection invalidates cache
"""

from unittest.mock import MagicMock, call, patch

import pytest

import ingest as ing
import rag


# ---------------------------------------------------------------------------
# Empty ChromaDB
# ---------------------------------------------------------------------------

class TestEmptyCollection:
    def test_query_on_empty_collection_returns_error_not_crash(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            result = rag.query("What are the risks?")
        assert result["response"] is None
        assert result["error"] is not None
        assert "No relevant content" in result["error"]

    def test_retrieve_on_empty_collection_returns_empty_list(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            chunks = rag.retrieve("query")
        assert chunks == []

    def test_get_collection_stats_on_empty_returns_not_ready(self, tmp_vector_dir):
        with patch("ingest.VECTOR_STORE_DIR", tmp_vector_dir):
            ing._collection_cache = None
            ing._stats_cache = None
            # Empty ChromaDB — no documents
            stats = ing.get_collection_stats()
        assert stats["ready"] is False
        assert stats["total_chunks"] == 0
        ing._collection_cache = None
        ing._stats_cache = None


# ---------------------------------------------------------------------------
# Query edge cases
# ---------------------------------------------------------------------------

class TestQueryEdgeCases:
    def test_very_long_query_does_not_crash(self):
        long_query = "investment risk " * 1000   # ~16,000 chars
        col = MagicMock()
        col.count.return_value = 0
        with patch("rag.get_collection", return_value=col):
            result = rag.query(long_query)
        assert result["response"] is None   # no docs → graceful error

    def test_empty_string_query(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            result = rag.query("")
        assert result["error"] is not None

    def test_unicode_query_does_not_crash(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            result = rag.query("¿Cuál es el riesgo de liquidez del fondo?")
        assert result["error"] is not None   # empty corpus → error, but no crash

    def test_query_with_special_chars_does_not_crash(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            result = rag.query("{injection} <script> & \"test\"")
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# API key missing
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    def test_rag_query_returns_error_when_key_missing(self, mock_collection, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rag._anthropic_client = None   # reset singleton

        with patch("rag.get_collection", return_value=mock_collection):
            result = rag.query("What is the expense ratio?")

        assert result["error"] is not None
        rag._anthropic_client = None   # clean up

    def test_classify_document_returns_other_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        ing._anthropic_client = None

        result = ing.classify_document("fund report text", "doc_name")
        assert result == "Other"
        ing._anthropic_client = None


# ---------------------------------------------------------------------------
# API call failures
# ---------------------------------------------------------------------------

class TestApiFailures:
    def test_rate_limit_returns_error_dict(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.side_effect = Exception("rate_limit_error")
            result = rag.query("question")
        assert result["response"] is None
        assert "Response generation failed" in result["error"]

    def test_network_timeout_returns_error_dict(self, mock_collection):
        import requests
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.side_effect = requests.Timeout("timed out")
            result = rag.query("question")
        assert result["error"] is not None

    def test_invalid_key_returns_error_dict(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.side_effect = Exception("authentication_error")
            result = rag.query("question")
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# Collection singleton caching
# ---------------------------------------------------------------------------

class TestCollectionSingleton:
    def test_get_collection_only_loads_model_once(self, tmp_vector_dir):
        """Multiple calls to get_collection() must return the same object."""
        ing._collection_cache = None
        ing._stats_cache = None

        with patch("ingest.chromadb.PersistentClient") as mock_chroma, \
             patch("ingest.embedding_functions.SentenceTransformerEmbeddingFunction") as mock_ef:
            mock_col = MagicMock()
            mock_chroma.return_value.get_or_create_collection.return_value = mock_col
            mock_ef.return_value = MagicMock()

            c1 = ing.get_collection()
            c2 = ing.get_collection()
            c3 = ing.get_collection()

        # Client and EF created only once, not three times
        assert mock_chroma.call_count == 1
        assert mock_ef.call_count == 1
        assert c1 is c2 is c3

        ing._collection_cache = None  # clean up

    def test_clear_collection_invalidates_cache(self, tmp_vector_dir):
        """After clear_collection(), next get_collection() call must rebuild."""
        ing._collection_cache = MagicMock()   # simulate cached collection
        ing._stats_cache = {"dummy": True}

        with patch("ingest.VECTOR_STORE_DIR", tmp_vector_dir), \
             patch("ingest.chromadb.PersistentClient") as mock_chroma:
            mock_chroma.return_value.delete_collection.return_value = None
            ing.clear_collection()

        assert ing._collection_cache is None
        assert ing._stats_cache is None


# ---------------------------------------------------------------------------
# Stats cache
# ---------------------------------------------------------------------------

class TestStatsCache:
    def test_stats_cached_after_first_call(self):
        mock_col = MagicMock()
        mock_col.count.return_value = 3
        mock_col.get.return_value = {
            "metadatas": [
                {"source": "doc_a", "asset_class": "US Equity"},
                {"source": "doc_b", "asset_class": "Fixed Income"},
                {"source": "doc_a", "asset_class": "US Equity"},
            ]
        }

        ing._stats_cache = None
        with patch("ingest.get_collection", return_value=mock_col), \
             patch("ingest.load_overrides", return_value={}):
            s1 = ing.get_collection_stats()
            s2 = ing.get_collection_stats()

        # get() should only be called once — second call uses cache
        assert mock_col.get.call_count == 1
        assert s1 is s2
        ing._stats_cache = None

    def test_invalidate_stats_cache_clears_it(self):
        ing._stats_cache = {"dummy": True}
        ing.invalidate_stats_cache()
        assert ing._stats_cache is None
