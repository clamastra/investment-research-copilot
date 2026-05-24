"""
ingest.py — PDF Ingestion Pipeline
-----------------------------------
Extracts text from PDFs, splits into overlapping chunks, generates local
embeddings via sentence-transformers, and indexes into ChromaDB on disk.

Each document is automatically classified into an asset class using Claude,
based on the first page of the document. This label is stored as metadata
on every chunk, enabling scoped retrieval at query time.

The embedding pipeline runs locally — no data leaves the machine during ingestion.
The only external call is the asset class classification (one Claude call per doc).
"""

import os
import fitz  # PyMuPDF
import chromadb
import anthropic
from chromadb.utils import embedding_functions
from pathlib import Path

# --- Environment -------------------------------------------------------------

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ[_key.strip()] = _val.strip()

# --- Paths -------------------------------------------------------------------

RAW_PDF_DIR = Path("data/raw_pdfs")
VECTOR_STORE_DIR = Path("vector_store")

# --- Asset class labels ------------------------------------------------------

ASSET_CLASSES = [
    "US Equity",
    "International Equity",
    "Fixed Income",
    "Multi-Asset",
    "Macro / Economic Outlook",
    "ESG / CSR",
    "Other",
]

# --- ChromaDB setup ----------------------------------------------------------

def get_collection():
    """
    Returns a persistent ChromaDB collection using local sentence-transformer
    embeddings. Creates the collection if it doesn't exist.
    """
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection = client.get_or_create_collection(
        name="investment_docs",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def clear_collection():
    """
    Wipes the ChromaDB collection entirely.
    Used before re-ingesting to avoid duplicate chunks or stale metadata.
    """
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    try:
        client.delete_collection("investment_docs")
        print("Vector store cleared.")
    except Exception:
        pass


# --- Asset class classification ----------------------------------------------

def classify_document(opening_text: str, doc_name: str) -> str:
    """
    Classifies a document into one of the predefined asset class labels using
    Claude Haiku. Uses the document filename as the primary signal and the
    first 3 pages of content as supporting evidence.

    Filename is weighted first because it is usually the most explicit indicator
    (e.g. 'Vanguard Total Bond Market Annual Report' is unambiguous even if the
    first pages are cover art or disclaimers).

    Constrained to max_tokens=20 so Claude cannot write explanations — only
    a label. Falls back to 'Other' if the response is unexpected or the API fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(f"  -> No API key found, defaulting to 'Other' for classification")
        return "Other"

    options = "\n".join(f"- {cls}" for cls in ASSET_CLASSES)
    prompt = f"""You are classifying an institutional investment document into exactly one asset class category.

Categories:
{options}

DOCUMENT FILENAME (primary signal — weight this heavily):
{doc_name}

OPENING CONTENT — first 3 pages (supporting evidence):
{opening_text[:4000]}

Instructions:
- The filename is usually the strongest indicator. Use it as your primary signal.
- Use the page content to resolve ambiguity if the filename is unclear.
- Respond with ONLY the category name. No explanation, no punctuation, nothing else.

Category:"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": prompt}],
        )
        label = response.content[0].text.strip()

        # Validate — if Claude returns something unexpected, fall back to Other
        if label in ASSET_CLASSES:
            return label
        else:
            print(f"  -> Unexpected classification '{label}', defaulting to 'Other'")
            return "Other"

    except Exception as e:
        print(f"  -> Classification failed ({e}), defaulting to 'Other'")
        return "Other"


# --- PDF extraction ----------------------------------------------------------

def extract_pages(pdf_path: Path) -> list[dict]:
    """
    Opens a PDF and extracts text page by page.
    Skips blank or near-blank pages.
    """
    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:  # skip only truly empty/whitespace-only pages
            pages.append({
                "page_num": i + 1,
                "text": text,
            })
    doc.close()
    return pages


# --- Chunking ----------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = 1500, overlap: int = 150) -> list[str]:
    """
    Splits text into overlapping character-based chunks.
    Overlap preserves context across chunk boundaries.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# --- Ingestion ---------------------------------------------------------------

def ingest_pdf(pdf_path: Path, collection) -> dict:
    """
    Ingests a single PDF into ChromaDB.
    Classifies the document by asset class using the first page.
    Stores source, page, file, and asset_class as metadata on every chunk.
    Returns a summary dict.
    """
    doc_name = pdf_path.stem
    print(f"\nIngesting: {pdf_path.name}")

    pages = extract_pages(pdf_path)
    if not pages:
        print(f"  -> No extractable text found. Skipping.")
        return {"chunks": 0, "asset_class": "Unknown"}

    # Classify using first 3 pages — covers title pages, TOCs, and slide decks
    first_pages_text = " ".join(p["text"] for p in pages[:3])
    asset_class = classify_document(first_pages_text, doc_name)
    print(f"  -> Classified as: {asset_class}")

    documents = []
    metadatas = []
    ids = []
    chunk_idx = 0

    for page in pages:
        chunks = chunk_text(page["text"])
        for chunk in chunks:
            documents.append(chunk)
            metadatas.append({
                "source": doc_name,
                "page": page["page_num"],
                "file": pdf_path.name,
                "asset_class": asset_class,   # scoped retrieval filter
            })
            ids.append(f"{doc_name}_p{page['page_num']}_c{chunk_idx}")
            chunk_idx += 1

    # Add to ChromaDB in batches
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        collection.add(
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
            ids=ids[i:i + batch_size],
        )

    print(f"  -> {len(pages)} pages, {chunk_idx} chunks indexed")
    return {"chunks": chunk_idx, "asset_class": asset_class}


def ingest_all(clear_first: bool = True) -> dict:
    """
    Ingests all PDFs in data/raw_pdfs/ into ChromaDB.
    Clears the collection first by default to avoid stale metadata.
    Returns a summary dict for UI display.
    """
    if clear_first:
        clear_collection()

    collection = get_collection()
    pdf_files = list(RAW_PDF_DIR.glob("*.pdf"))

    if not pdf_files:
        return {"error": f"No PDFs found in {RAW_PDF_DIR}"}

    results = {}
    total_chunks = 0

    for pdf_path in pdf_files:
        result = ingest_pdf(pdf_path, collection)
        results[pdf_path.name] = result
        total_chunks += result["chunks"]

    summary = {
        "docs_ingested": len(pdf_files),
        "total_chunks": total_chunks,
        "results": results,
    }

    print(f"\nDone. {len(pdf_files)} documents, {total_chunks} total chunks indexed.")
    return summary


def get_collection_stats() -> dict:
    """
    Returns current stats and the list of unique documents and asset classes
    in the vector store. Used to populate UI filters.
    """
    try:
        collection = get_collection()
        count = collection.count()
        if count == 0:
            return {"total_chunks": 0, "ready": False, "documents": [], "asset_classes": []}

        # Sample metadata to get unique values for filters
        sample = collection.get(limit=count, include=["metadatas"])

        # Build a mapping of document -> asset_class for UI filtering
        doc_class_map = {}
        for m in sample["metadatas"]:
            src = m.get("source", "Unknown")
            cls = m.get("asset_class", "Unknown")
            doc_class_map[src] = cls

        docs = sorted(doc_class_map.keys())
        classes = sorted(set(doc_class_map.values()))

        return {
            "total_chunks": count,
            "ready": True,
            "documents": docs,
            "asset_classes": classes,
            "doc_class_map": doc_class_map,  # doc name -> asset class
        }
    except Exception:
        return {"total_chunks": 0, "ready": False, "documents": [], "asset_classes": [], "doc_class_map": {}}


# --- Run directly ------------------------------------------------------------

if __name__ == "__main__":
    print("CapitalContext -- Ingestion Pipeline")
    print("=" * 40)
    summary = ingest_all()
    if "error" in summary:
        print(f"Error: {summary['error']}")
    else:
        print(f"\nSummary:")
        print(f"  Documents: {summary['docs_ingested']}")
        print(f"  Total chunks: {summary['total_chunks']}")
        for fname, res in summary["results"].items():
            print(f"  {fname}: {res['chunks']} chunks ({res['asset_class']})")
