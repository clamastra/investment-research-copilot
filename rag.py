"""
rag.py — Retrieval-Augmented Generation Pipeline
--------------------------------------------------
Retrieves semantically relevant chunks from ChromaDB and generates
source-grounded responses using the Claude API.

Flow:
  user query -> embed query -> ChromaDB similarity search -> top-k chunks
  -> format as labeled source block -> Claude API -> grounded response
"""

import os
from pathlib import Path
import anthropic
from dotenv import load_dotenv
from ingest import get_collection, load_overrides
from prompts import QA_PROMPT, MEMO_PROMPT, RISK_PROMPT, COMPARISON_PROMPT

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# --- Anthropic client singleton ----------------------------------------------

_anthropic_client: anthropic.Anthropic | None = None

def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not found. Create a .env file and add your key."
            )
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


# --- Configuration -----------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"  # swap to claude-sonnet-4-6 for higher quality
MAX_TOKENS = 2048
DEFAULT_N_RESULTS = 10   # candidate chunks to retrieve before threshold filtering
DISTANCE_THRESHOLD = 0.7 # cosine distance cutoff — chunks above this are too dissimilar
                          # to be useful. Range is 0 (identical) to 2 (opposite).
                          # 0.7 is a reasonable starting point for institutional documents.

# Maps UI dropdown labels to prompt templates
PROMPT_MAP = {
    "Q&A with citations": QA_PROMPT,
    "IC Memo draft": MEMO_PROMPT,
    "Risk summary": RISK_PROMPT,
    "Manager comparison": COMPARISON_PROMPT,
}

# --- Step 1: Retrieval -------------------------------------------------------

def retrieve(
    query: str,
    n_results: int = DEFAULT_N_RESULTS,
    asset_class: str = None,
    source: str = None,
) -> list[dict]:
    """
    Embeds the user query and retrieves the n most semantically similar chunks
    from ChromaDB, with optional pre-filtering by asset class or document name.

    Pre-filtering (the 'where' clause) scopes the search to a subset of the
    collection before similarity search runs. This is more efficient than
    post-filtering and prevents irrelevant documents from polluting results.

    Filter priority: source (specific doc) > asset_class > no filter (all docs)

    Two-stage retrieval:
    1. Pre-filter by metadata (optional), then fetch n_results candidates
    2. Post-filter by DISTANCE_THRESHOLD — removes low-relevance chunks
    """
    collection = get_collection()

    if collection.count() == 0:
        return []

    n = min(n_results, collection.count())

    # Build metadata filter — ChromaDB 'where' clause
    # When filtering by asset class, account for manual overrides:
    # some docs may have a different asset_class stored in ChromaDB
    # but have been overridden by the user. Filter by source name for those.
    where = None
    if source:
        where = {"source": {"$eq": source}}
    elif asset_class and asset_class != "All Documents":
        overrides = load_overrides()
        overridden_to_class = [
            doc for doc, cls in overrides.items() if cls == asset_class
        ]
        if overridden_to_class:
            # Include docs stored with this asset_class OR overridden to it
            where = {"$or": [
                {"asset_class": {"$eq": asset_class}},
                {"source": {"$in": overridden_to_class}},
            ]}
        else:
            where = {"asset_class": {"$eq": asset_class}}

    # ChromaDB raises if n_results > number of documents matching the where filter.
    # We know total collection count but not filtered count, so catch and retry.
    try:
        results = collection.query(
            query_texts=[query],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        if "Number of requested results" in str(e) and n > 1:
            results = collection.query(
                query_texts=[query],
                n_results=1,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        else:
            raise

    chunks = []
    for i, doc in enumerate(results["documents"][0]):
        distance = round(results["distances"][0][i], 4)

        if distance > DISTANCE_THRESHOLD:
            continue

        meta = results["metadatas"][0][i]
        chunks.append({
            "text":         doc,
            "source":       meta["source"],
            "source_label": meta.get("source_label", ""),
            "company_name": meta.get("company_name", ""),
            "filing_type":  meta.get("filing_type", ""),
            "period":       meta.get("period", ""),
            "filed_date":   meta.get("filed_date", ""),
            "page":         meta["page"],
            "file":         meta["file"],
            "asset_class":  meta.get("asset_class", "Unknown"),
            "distance":     distance,
        })

    return chunks


# --- Step 2: Context formatting ----------------------------------------------

def format_context(chunks: list[dict]) -> str:
    """
    Formats retrieved chunks into a numbered, labeled source block for the prompt.

    Uses source_label when available ("Pimco Funds — N-CSR (2025-11-30)"),
    falling back to the raw source slug for legacy chunks without the field.
    The page number is always appended so Claude can cite specific pages.

    The separator between chunks helps the model distinguish where one
    source ends and another begins.
    """
    parts = []
    for chunk in chunks:
        display = chunk.get("source_label") or chunk["source"]
        label = f"[{display} | Page {chunk['page']}]"
        parts.append(f"{label}\n{chunk['text']}")

    return "\n\n---\n\n".join(parts)


# --- Step 3: Response generation ---------------------------------------------

def generate_response(query: str, chunks: list[dict], mode: str) -> str:
    """
    Sends the formatted source context + user query to Claude using the
    prompt template for the selected output mode.

    The prompt templates (in prompts.py) instruct Claude to:
    - Answer only from the provided sources
    - Cite each source by name and page
    - Explicitly state when information is not found in the sources

    This is the hallucination control mechanism.
    """
    client = _get_anthropic_client()
    context = format_context(chunks)

    # Select the right prompt template for the output mode
    prompt_template = PROMPT_MAP.get(mode, QA_PROMPT)
    # Escape braces in context so .format() doesn't misinterpret {ticker} or
    # similar strings in source documents as template placeholders.
    safe_context = context.replace("{", "{{").replace("}", "}}")
    prompt = prompt_template.format(context=safe_context, question=query)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


# --- Full pipeline ------------------------------------------------------------

def query(
    question: str,
    mode: str = "Q&A with citations",
    n_results: int = DEFAULT_N_RESULTS,
    asset_class: str = None,
    source: str = None,
) -> dict:
    """
    Full RAG pipeline entry point.

    1. Retrieve relevant chunks from ChromaDB (with optional scope filters)
    2. Generate a grounded response via Claude API
    3. Return response text + source chunks for display and citation

    asset_class: filter to a specific asset class (e.g. "Fixed Income")
    source: filter to a specific document (e.g. "Vanguard 500 Index Annual Report")

    Returns a dict with keys: response, sources, mode, error
    """
    chunks = retrieve(question, n_results, asset_class=asset_class, source=source)

    if not chunks:
        scope = source or asset_class or "all documents"
        return {
            "response": None,
            "sources": [],
            "mode": mode,
            "error": f"No relevant content found in {scope}. Try broadening your scope or rephrasing your query.",
        }

    try:
        response_text = generate_response(question, chunks, mode)
    except Exception as e:
        return {
            "response": None,
            "sources": chunks,
            "mode": mode,
            "error": f"Response generation failed: {e}",
        }

    return {
        "response": response_text,
        "sources": chunks,
        "mode": mode,
        "error": None,
    }
