"""
ingest.py — PDF Ingestion Pipeline
-----------------------------------
Extracts text from PDFs, splits into overlapping chunks, generates local
embeddings via sentence-transformers, and indexes into ChromaDB on disk.

The entire pipeline runs locally — no data leaves the machine during ingestion.
"""

import fitz  # PyMuPDF
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

# --- Paths -------------------------------------------------------------------

RAW_PDF_DIR = Path("data/raw_pdfs")
VECTOR_STORE_DIR = Path("vector_store")

# --- ChromaDB setup ----------------------------------------------------------

def get_collection():
    """
    Returns a persistent ChromaDB collection using local sentence-transformer
    embeddings. Creates the collection if it doesn't exist.
    """
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))

    # Local embedding model — runs on device, no API call required
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection = client.get_or_create_collection(
        name="investment_docs",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},  # cosine similarity for semantic search
    )
    return collection


# --- PDF extraction ----------------------------------------------------------

def extract_pages(pdf_path: Path) -> list[dict]:
    """
    Opens a PDF and extracts text page by page.
    Returns a list of dicts with page number and text.
    Skips blank or near-blank pages.
    """
    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if len(text) > 50:  # skip pages with negligible content
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

    chunk_size: target characters per chunk (~375 tokens)
    overlap: characters shared between adjacent chunks to preserve context
             across boundaries

    Overlap matters: without it, a sentence split across two chunk boundaries
    would lose context on both sides.
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

def ingest_pdf(pdf_path: Path, collection) -> int:
    """
    Ingests a single PDF into ChromaDB.
    Returns the number of chunks indexed.
    """
    doc_name = pdf_path.stem  # filename without extension
    print(f"\nIngesting: {pdf_path.name}")

    pages = extract_pages(pdf_path)
    if not pages:
        print(f"  -> No extractable text found. Skipping.")
        return 0

    documents = []
    metadatas = []
    ids = []
    chunk_idx = 0

    for page in pages:
        chunks = chunk_text(page["text"])
        for chunk in chunks:
            documents.append(chunk)
            metadatas.append({
                "source": doc_name,           # document name for citations
                "page": page["page_num"],     # page number for citations
                "file": pdf_path.name,        # original filename
            })
            ids.append(f"{doc_name}_p{page['page_num']}_c{chunk_idx}")
            chunk_idx += 1

    # Add to ChromaDB in batches of 100 to avoid memory spikes
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        collection.add(
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
            ids=ids[i:i + batch_size],
        )

    print(f"  -> {len(pages)} pages extracted, {chunk_idx} chunks indexed")
    return chunk_idx


def ingest_all() -> dict:
    """
    Ingests all PDFs found in data/raw_pdfs/ into ChromaDB.
    Returns a summary dict for UI display.
    """
    collection = get_collection()
    pdf_files = list(RAW_PDF_DIR.glob("*.pdf"))

    if not pdf_files:
        return {"error": f"No PDFs found in {RAW_PDF_DIR}"}

    results = {}
    total_chunks = 0

    for pdf_path in pdf_files:
        chunks = ingest_pdf(pdf_path, collection)
        results[pdf_path.name] = chunks
        total_chunks += chunks

    summary = {
        "docs_ingested": len(pdf_files),
        "total_chunks": total_chunks,
        "results": results,
    }

    print(f"\nDone. {len(pdf_files)} documents, {total_chunks} total chunks indexed.")
    return summary


def get_collection_stats() -> dict:
    """
    Returns current stats about what's in the vector store.
    Useful for the UI to show whether documents are loaded.
    """
    try:
        collection = get_collection()
        count = collection.count()
        return {"total_chunks": count, "ready": count > 0}
    except Exception:
        return {"total_chunks": 0, "ready": False}


# --- Run directly ------------------------------------------------------------

if __name__ == "__main__":
    print("CapitalContext — Ingestion Pipeline")
    print("=" * 40)
    summary = ingest_all()
    if "error" in summary:
        print(f"Error: {summary['error']}")
    else:
        print(f"\nSummary:")
        print(f"  Documents: {summary['docs_ingested']}")
        print(f"  Total chunks: {summary['total_chunks']}")
