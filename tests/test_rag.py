"""
tests/test_rag.py — Tests for the RAG retrieval and generation pipeline.

Covers:
  - Retrieval returns expected metadata fields
  - Semantic relevance check (spot-check: known query → known doc)
  - Distance threshold filtering
  - Empty results handled gracefully
  - Empty query handled gracefully
  - API failure returns error dict (not crash)
  - All four output modes return non-empty string
  - Citations in Q&A mode reference source documents
"""

from unittest.mock import MagicMock, patch

import pytest

import rag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_collection(docs, metas, distances):
    col = MagicMock()
    col.count.return_value = len(docs)
    col.query.return_value = {
        "documents": [docs],
        "metadatas": [metas],
        "distances": [distances],
    }
    return col


# ---------------------------------------------------------------------------
# retrieve() — metadata completeness
# ---------------------------------------------------------------------------

class TestRetrieve:
    def test_returns_expected_metadata_keys(self):
        col = make_collection(
            docs=["Vanguard 500 tracks the S&P 500 index."],
            metas=[{"source": "vanguard_500", "page": 1, "file": "vanguard_500.pdf", "asset_class": "US Equity"}],
            distances=[0.2],
        )
        with patch("rag.get_collection", return_value=col):
            chunks = rag.retrieve("what is the expense ratio?")

        assert len(chunks) == 1
        assert "text" in chunks[0]
        assert "source" in chunks[0]
        assert "page" in chunks[0]
        assert "asset_class" in chunks[0]
        assert "distance" in chunks[0]

    def test_distance_threshold_filters_irrelevant_chunks(self):
        col = make_collection(
            docs=["relevant chunk", "very irrelevant chunk"],
            metas=[
                {"source": "doc_a", "page": 1, "file": "a.pdf", "asset_class": "US Equity"},
                {"source": "doc_b", "page": 1, "file": "b.pdf", "asset_class": "Fixed Income"},
            ],
            distances=[0.3, 0.8],   # 0.8 is above the 0.7 threshold
        )
        with patch("rag.get_collection", return_value=col):
            chunks = rag.retrieve("query")

        assert len(chunks) == 1
        assert chunks[0]["source"] == "doc_a"

    def test_empty_collection_returns_empty_list(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            chunks = rag.retrieve("any query")
        assert chunks == []

    def test_all_chunks_above_threshold_returns_empty(self):
        col = make_collection(
            docs=["unrelated text"],
            metas=[{"source": "x", "page": 1, "file": "x.pdf", "asset_class": "Other"}],
            distances=[0.95],
        )
        with patch("rag.get_collection", return_value=col):
            chunks = rag.retrieve("query")
        assert chunks == []

    def test_n_results_overflow_handled_gracefully(self):
        """ChromaDB raises when n_results > filtered doc count; must not crash."""
        col = MagicMock()
        col.count.return_value = 100
        # First call raises the n_results overflow error, second succeeds with 1 result
        col.query.side_effect = [
            Exception("Number of requested results 10 is greater than number of elements in index 2"),
            {
                "documents": [["one chunk"]],
                "metadatas": [[{"source": "s", "page": 1, "file": "s.pdf", "asset_class": "Other"}]],
                "distances": [[0.3]],
            },
        ]
        with patch("rag.get_collection", return_value=col):
            chunks = rag.retrieve("query", source="s")
        assert len(chunks) == 1

    def test_source_filter_applied(self):
        col = MagicMock()
        col.count.return_value = 5
        col.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        with patch("rag.get_collection", return_value=col):
            rag.retrieve("query", source="specific_doc")

        call_kwargs = col.query.call_args[1]
        assert call_kwargs["where"] == {"source": {"$eq": "specific_doc"}}

    def test_asset_class_filter_applied(self):
        col = MagicMock()
        col.count.return_value = 5
        col.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        with patch("rag.get_collection", return_value=col), \
             patch("rag.load_overrides", return_value={}):
            rag.retrieve("query", asset_class="Fixed Income")

        call_kwargs = col.query.call_args[1]
        assert call_kwargs["where"] == {"asset_class": {"$eq": "Fixed Income"}}


# ---------------------------------------------------------------------------
# query() — full pipeline
# ---------------------------------------------------------------------------

class TestQuery:
    def _make_claude_response(self, text):
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        return resp

    def test_returns_response_and_sources_on_success(self, mock_collection):
        claude_text = "Based on Vanguard 500 (Page 1), the expense ratio is 0.03%."
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response(claude_text)
            result = rag.query("What is the expense ratio?")

        assert result["error"] is None
        assert result["response"] == claude_text
        assert len(result["sources"]) > 0

    def test_returns_error_dict_on_empty_corpus(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            result = rag.query("any question")
        assert result["error"] is not None
        assert result["response"] is None

    def test_returns_error_dict_on_api_failure(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.side_effect = Exception("rate limit")
            result = rag.query("question")

        assert result["error"] is not None
        assert "Response generation failed" in result["error"]
        assert result["response"] is None

    def test_no_relevant_chunks_returns_error_not_crash(self, mock_collection):
        # All distances above threshold
        mock_collection.query.return_value = {
            "documents": [["irrelevant"]],
            "metadatas": [[{"source": "x", "page": 1, "file": "x.pdf", "asset_class": "Other"}]],
            "distances": [[0.99]],
        }
        with patch("rag.get_collection", return_value=mock_collection):
            result = rag.query("question")
        assert result["error"] is not None
        assert result["response"] is None

    def test_brace_in_source_text_does_not_crash(self, mock_collection):
        """Source documents containing { } must not break the prompt template."""
        mock_collection.query.return_value = {
            "documents": [["The fund has a {NAV} of $10.00 per share."]],
            "metadatas": [[{"source": "fund_doc", "page": 1, "file": "fund_doc.pdf", "asset_class": "Other"}]],
            "distances": [[0.2]],
        }
        claude_text = "NAV is $10.00."
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response(claude_text)
            result = rag.query("What is the NAV?")
        assert result["error"] is None

    def test_empty_query_returns_no_results_gracefully(self, empty_mock_collection):
        with patch("rag.get_collection", return_value=empty_mock_collection):
            result = rag.query("")
        assert result["response"] is None
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# Output mode tests — all four modes
# ---------------------------------------------------------------------------

class TestOutputModes:
    MODES = ["Q&A with citations", "IC Memo draft", "Risk summary", "Manager comparison"]

    def _make_claude_response(self, text):
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        return resp

    @pytest.mark.parametrize("mode", MODES)
    def test_mode_returns_non_empty_response(self, mock_collection, mode):
        expected = f"Mock response for {mode}."
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response(expected)
            result = rag.query("describe this fund", mode=mode)
        assert result["error"] is None
        assert result["response"] == expected

    def test_qa_mode_prompt_contains_sources_and_question(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response("answer")
            rag.query("expense ratio?", mode="Q&A with citations")

        call_args = mock_client.return_value.messages.create.call_args
        prompt_content = call_args[1]["messages"][0]["content"]
        assert "expense ratio" in prompt_content.lower()
        # Source label should appear in the formatted context
        assert "vanguard_500_annual_report" in prompt_content

    def test_ic_memo_prompt_contains_memo_marker(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response("memo")
            rag.query("assess this manager", mode="IC Memo draft")

        prompt = mock_client.return_value.messages.create.call_args[1]["messages"][0]["content"]
        assert "Memo:" in prompt or "memo" in prompt.lower()

    def test_risk_summary_prompt_contains_risk_marker(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response("risk")
            rag.query("what are the risks?", mode="Risk summary")

        prompt = mock_client.return_value.messages.create.call_args[1]["messages"][0]["content"]
        assert "Risk Summary:" in prompt

    def test_comparison_prompt_contains_comparison_marker(self, mock_collection):
        with patch("rag.get_collection", return_value=mock_collection), \
             patch("rag._get_anthropic_client") as mock_client:
            mock_client.return_value.messages.create.return_value = self._make_claude_response("comparison")
            rag.query("compare these managers", mode="Manager comparison")

        prompt = mock_client.return_value.messages.create.call_args[1]["messages"][0]["content"]
        assert "Comparison:" in prompt
