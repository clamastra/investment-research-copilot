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
from dotenv import load_dotenv
import anthropic
from ingest import get_collection
from prompts import QA_PROMPT, MEMO_PROMPT, RISK_PROMPT, COMPARISON_PROMPT

load_dotenv()

# --- Configuration -----------------------------------------------------------

MODEL = "claude-3-5-haiku-20241022"  # swap to sonnet/opus for higher quality
MAX_TOKENS = 2048
DEFAULT_N_RESULTS = 5  # number of chunks to retrieve per query

# Maps UI dropdown labels to prompt templates
PROMPT_MAP = {
    "Q&A with citations": QA_PROMPT,
    "IC Memo draft": MEMO_PROMPT,
    "Risk summary": RISK_PROMPT,
    "Manager comparison": COMPARISON_PROMPT,
}

# --- Step 1: Retrieval -------------------------------------------------------

def retrieve(query: str, n_results: int = DEFAULT_N_RESULTS) -> list[dict]:
    """
    Embeds the user query and retrieves the n most semantically similar chunks
    from ChromaDB. Returns chunks with their text, source, page, and similarity score.

    ChromaDB uses the same embedding model as ingestion (all-MiniLM-L6-v2),
    so query and document vectors are comparable.

    Distance score: lower = more similar. Cosine distance of 0 = identical.
    """
    collection = get_collection()

    if collection.count() == 0:
        return []

    # Cap n_results at collection size to avoid ChromaDB errors on small collections
    n = min(n_results, collection.count())

    results = collection.query(
        query_texts=[query],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for i, doc in enumerate(results["documents"][0]):
        chunks.append({
            "text": doc,
            "source": results["metadatas"][0][i]["source"],
            "page": results["metadatas"][0][i]["page"],
            "file": results["metadatas"][0][i]["file"],
            "distance": round(results["distances"][0][i], 4),
        })

    return chunks


# --- Step 2: Context formatting ----------------------------------------------

def format_context(chunks: list[dict]) -> str:
    """
    Formats retrieved chunks into a numbered, labeled source block for the prompt.

    Each chunk is labeled with its document name and page number.
    This is what makes citations possible — Claude can reference
    [Source 1: vanguard_outlook, Page 3] in its response.

    The separator between chunks helps the model distinguish where one
    source ends and another begins.
    """
    parts = []
    for i, chunk in enumerate(chunks):
        label = f"[Source {i + 1}: {chunk['source']}, Page {chunk['page']}]"
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
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY not found. Create a .env file and add your key."
        )

    client = anthropic.Anthropic(api_key=api_key)
    context = format_context(chunks)

    # Select the right prompt template for the output mode
    prompt_template = PROMPT_MAP.get(mode, QA_PROMPT)
    prompt = prompt_template.format(context=context, question=query)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


# --- Full pipeline ------------------------------------------------------------

def query(question: str, mode: str = "Q&A with citations", n_results: int = DEFAULT_N_RESULTS) -> dict:
    """
    Full RAG pipeline entry point.

    1. Retrieve relevant chunks from ChromaDB
    2. Generate a grounded response via Claude API
    3. Return response text + source chunks for display and citation

    Returns a dict with keys: response, sources, mode, error
    """
    chunks = retrieve(question, n_results)

    if not chunks:
        return {
            "response": None,
            "sources": [],
            "mode": mode,
            "error": "No documents found in the knowledge base. Please ingest PDFs first.",
        }

    response_text = generate_response(question, chunks, mode)

    return {
        "response": response_text,
        "sources": chunks,
        "mode": mode,
        "error": None,
    }
