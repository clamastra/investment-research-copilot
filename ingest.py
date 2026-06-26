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
import json
import re
import fitz  # PyMuPDF
import chromadb
import anthropic
from chromadb.utils import embedding_functions
from html.parser import HTMLParser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# --- Paths -------------------------------------------------------------------

# Anchored to this file's directory so imports from sibling projects work
# regardless of the caller's working directory.
_HERE = Path(__file__).resolve().parent
RAW_PDF_DIR      = _HERE / "data" / "raw_pdfs"
VECTOR_STORE_DIR = _HERE / "vector_store"
OVERRIDES_PATH   = VECTOR_STORE_DIR / "classification_overrides.json"

# --- Anthropic client --------------------------------------------------------

# Module-level singleton — avoids repeated client initialization on every
# classify_document() call (one call per document during ingest).
_anthropic_client: anthropic.Anthropic | None = None

def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic_client


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

# --- Classification overrides ------------------------------------------------

def load_overrides() -> dict:
    """
    Loads manual classification overrides from disk.
    Returns a dict mapping document name -> asset class.
    Overrides are applied on top of auto-classification — they always win.
    """
    if OVERRIDES_PATH.exists():
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_override(doc_name: str, asset_class: str) -> None:
    """
    Saves a manual classification override for a document.
    Creates the overrides file if it doesn't exist.
    """
    VECTOR_STORE_DIR.mkdir(exist_ok=True)
    overrides = load_overrides()
    overrides[doc_name] = asset_class
    with open(OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)


# --- ChromaDB setup ----------------------------------------------------------

# Module-level singleton — the sentence-transformer model is 90MB and takes
# 0.5–2s to load. Re-creating it on every call (every Streamlit rerender, every
# query) is the single biggest performance drain in the pipeline.
_collection_cache = None

def get_collection():
    """
    Returns a persistent ChromaDB collection using local sentence-transformer
    embeddings. Creates the collection if it doesn't exist.
    Lazy-initializes and caches on first call; reuses for all subsequent calls.
    """
    global _collection_cache
    if _collection_cache is None:
        client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        _collection_cache = client.get_or_create_collection(
            name="investment_docs",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection_cache


def clear_collection():
    """
    Wipes the ChromaDB collection entirely.
    Used before re-ingesting to avoid duplicate chunks or stale metadata.
    Resets the module-level cache so the next get_collection() call rebuilds it.
    """
    global _collection_cache, _stats_cache
    _collection_cache = None
    _stats_cache = None
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_DIR))
    try:
        client.delete_collection("investment_docs")
        print("Vector store cleared.")
    except Exception as e:
        print(f"Warning: could not clear collection: {e}")


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

Filename pattern examples:
- "500 Index", "S&P", "Large Cap Growth", "US Equity Fund" -> US Equity
- "International", "Emerging Markets", "Global ex-US", "EAFE" -> International Equity
- "Bond", "Fixed Income", "Treasury", "Credit", "Total Bond" -> Fixed Income
- "Balanced", "Target Date", "Multi-Asset", "Allocation" -> Multi-Asset
- "Outlook", "Economic", "Market Outlook", "Macro", "Forecast" -> Macro / Economic Outlook
- "CSR", "Sustainability", "ESG", "Responsible", "Impact" -> ESG / CSR

DOCUMENT FILENAME (primary signal — weight this heavily):
{doc_name}

OPENING CONTENT — first 3 pages (supporting evidence):
{opening_text[:4000]}

Instructions:
- The filename is the strongest indicator. Use the pattern examples above to guide you.
- Use page content only to resolve ambiguity when the filename is unclear.
- Respond with ONLY the category name. No explanation, no punctuation, nothing else.

Category:"""

    try:
        client = _get_anthropic_client()
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


# --- HTML extraction ---------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Strips tags from SEC HTML filings, collecting visible text content."""
    _SKIP = {"script", "style", "head", "meta", "link", "noscript"}
    _BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "li", "br", "td", "th"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._buf = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        # Any namespace-prefixed tag (ix:*, xbrli:*, dei:*, etc.) is an iXBRL
        # element — its text content is XBRL metadata, not readable prose. Skip it.
        if ":" in tag:
            self._skip_depth += 1
            return
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK and self._buf:
            text = " ".join(self._buf).strip()
            if text:
                self.paragraphs.append(text)
            self._buf = []

    def handle_endtag(self, tag):
        if ":" in tag:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if not self._skip_depth:
            text = data.strip()
            if text:
                self._buf.append(text)

    def get_text(self) -> str:
        if self._buf:
            text = " ".join(self._buf).strip()
            if text:
                self.paragraphs.append(text)
        return "\n".join(self.paragraphs)


_HTML_VIRTUAL_PAGE = 3000  # characters per virtual "page" for citation purposes

def extract_html_pages(html_path: Path) -> list[dict]:
    """
    Extracts text from an SEC HTML filing and divides it into virtual pages.
    Virtual pages preserve the citation (Page N) format used by the RAG pipeline.
    EDGAR HTML filings can be large (10MB+) — text extraction trims noise.
    """
    with open(html_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    extractor = _HTMLTextExtractor()
    extractor.feed(content)
    full_text = extractor.get_text()

    if not full_text.strip():
        return []

    pages = []
    start = 0
    page_num = 1
    while start < len(full_text):
        chunk = full_text[start : start + _HTML_VIRTUAL_PAGE].strip()
        if chunk:
            pages.append({"page_num": page_num, "text": chunk})
        start += _HTML_VIRTUAL_PAGE
        page_num += 1

    return pages


# --- PDF extraction ----------------------------------------------------------

def extract_pages(pdf_path: Path) -> list[dict]:
    """
    Opens a PDF and extracts text page by page.
    Skips blank or near-blank pages.
    Returns empty list if the PDF cannot be opened (corrupt, encrypted, etc.).
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"  -> Cannot open PDF ({e}). Skipping.")
        return []

    pages = []
    for i, page in enumerate(doc):
        try:
            text = page.get_text().strip()
        except Exception:
            continue
        if text:
            pages.append({"page_num": i + 1, "text": text})
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


# --- Document identity helpers -----------------------------------------------

def _read_sidecar(doc_path: Path) -> dict | None:
    """
    Looks for a .meta.json sidecar alongside the document file.
    Returns the parsed dict or None if no sidecar exists.
    Sidecars are written by sourcing.download_pdf() for EDGAR downloads.
    """
    sidecar = doc_path.parent / f"{doc_path.stem}.meta.json"
    if sidecar.exists():
        try:
            with open(sidecar, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _extract_doc_identity(first_page_text: str, doc_name: str, sidecar_path: Path) -> dict:
    """
    Fires a single Claude Haiku call on the first page of a document to extract:
      - company_name  (e.g. "T. Rowe Price Group Inc.")
      - filing_type   (e.g. "Annual Report", "Fund Shareholder Report", "10-K")
      - period        (e.g. "December 31, 2025" or "2025-12-31"; "Unknown" if absent)

    Writes the result as a .meta.json sidecar so re-ingestion skips this call.
    Falls back to filename-derived values if the API call fails or key is missing.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    fallback = {
        "company_name": doc_name.replace("_", " "),
        "filing_type":  "Investment Document",
        "period":       "Unknown",
        "filed_date":   "",
        "source_label": doc_name.replace("_", " "),
    }

    if not api_key:
        return fallback

    prompt = f"""You are extracting identity metadata from the opening page of an investment document.

Extract exactly three fields from the text below:
1. company_name — The issuing company, fund family, or adviser (e.g. "T. Rowe Price Group Inc.", "PIMCO Funds", "Vanguard").
2. filing_type  — The type of document in plain English (e.g. "Annual Shareholder Report", "Quarterly Report", "Annual Report (10-K)", "Investment Adviser Registration (ADV)").
3. period       — The period or date the document covers (e.g. "December 31, 2025", "September 30, 2025"). If no period is visible, respond "Unknown".

Document name (use as fallback context if the text is a cover page with little text):
{doc_name}

Opening page text:
{first_page_text[:3000]}

Respond in this exact JSON format with no other text:
{{"company_name": "...", "filing_type": "...", "period": "..."}}"""

    try:
        client = _get_anthropic_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        company = str(data.get("company_name", "") or fallback["company_name"]).strip()
        ftype   = str(data.get("filing_type",  "") or fallback["filing_type"]).strip()
        period  = str(data.get("period",        "") or "Unknown").strip()

        period_part  = f" ({period})" if period and period != "Unknown" else ""
        source_label = f"{company} — {ftype}{period_part}"

        result = {
            "company_name": company,
            "filing_type":  ftype,
            "period":       period,
            "filed_date":   "",
            "source_label": source_label,
        }

        try:
            sidecar_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except Exception:
            pass  # sidecar write failure is non-fatal

        return result

    except Exception as e:
        print(f"  -> Identity extraction failed ({e}), using filename fallback")
        return fallback


def _get_doc_identity(doc_path: Path, first_page_text: str) -> dict:
    """
    Returns identity metadata for a document — from sidecar if available,
    otherwise fires _extract_doc_identity() and caches the result as a sidecar.
    """
    sidecar = _read_sidecar(doc_path)
    if sidecar:
        return sidecar
    sidecar_path = doc_path.parent / f"{doc_path.stem}.meta.json"
    print(f"  -> No sidecar found, extracting identity via LLM...")
    return _extract_doc_identity(first_page_text, doc_path.stem, sidecar_path)


# --- Ingestion ---------------------------------------------------------------

def ingest_pdf(pdf_path: Path, collection) -> dict:
    """
    Ingests a single PDF into ChromaDB.
    Classifies the document by asset class using the first page.
    Stores source, page, file, asset_class, source_label, company_name,
    filing_type, period, and filed_date as metadata on every chunk.
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

    # Enrich with human-readable identity (sidecar or LLM extraction)
    identity = _get_doc_identity(pdf_path, pages[0]["text"] if pages else "")
    print(f"  -> Label: {identity['source_label']}")

    documents = []
    metadatas = []
    ids = []
    chunk_idx = 0

    for page in pages:
        chunks = chunk_text(page["text"])
        for chunk in chunks:
            documents.append(chunk)
            metadatas.append({
                "source":       doc_name,
                "source_label": identity["source_label"],
                "company_name": identity["company_name"],
                "filing_type":  identity["filing_type"],
                "period":       identity["period"],
                "filed_date":   identity["filed_date"],
                "page":         page["page_num"],
                "file":         pdf_path.name,
                "asset_class":  asset_class,
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


def ingest_html(html_path: Path, collection) -> dict:
    """
    Ingests a single HTML file (SEC filing) into ChromaDB.
    Mirrors ingest_pdf — same classification, chunking, and metadata structure,
    including source_label, company_name, filing_type, period, and filed_date.
    """
    doc_name = html_path.stem
    print(f"\nIngesting (HTML): {html_path.name}")

    pages = extract_html_pages(html_path)
    if not pages:
        print(f"  -> No extractable text found. Skipping.")
        return {"chunks": 0, "asset_class": "Unknown"}

    first_pages_text = " ".join(p["text"] for p in pages[:3])
    asset_class = classify_document(first_pages_text, doc_name)
    print(f"  -> Classified as: {asset_class}")

    # Enrich with human-readable identity (sidecar or LLM extraction)
    identity = _get_doc_identity(html_path, pages[0]["text"] if pages else "")
    print(f"  -> Label: {identity['source_label']}")

    documents, metadatas, ids = [], [], []
    chunk_idx = 0

    for page in pages:
        for chunk in chunk_text(page["text"]):
            documents.append(chunk)
            metadatas.append({
                "source":       doc_name,
                "source_label": identity["source_label"],
                "company_name": identity["company_name"],
                "filing_type":  identity["filing_type"],
                "period":       identity["period"],
                "filed_date":   identity["filed_date"],
                "page":         page["page_num"],
                "file":         html_path.name,
                "asset_class":  asset_class,
            })
            ids.append(f"{doc_name}_p{page['page_num']}_c{chunk_idx}")
            chunk_idx += 1

    batch_size = 100
    for i in range(0, len(documents), batch_size):
        collection.add(
            documents=documents[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
            ids=ids[i : i + batch_size],
        )

    print(f"  -> {len(pages)} virtual pages, {chunk_idx} chunks indexed")
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
    pdf_files  = list(RAW_PDF_DIR.glob("*.pdf"))
    html_files = list(RAW_PDF_DIR.glob("*.htm")) + list(RAW_PDF_DIR.glob("*.html"))
    all_files  = pdf_files + html_files

    if not all_files:
        return {"error": f"No documents found in {RAW_PDF_DIR}"}

    results = {}
    total_chunks = 0

    for path in all_files:
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                result = ingest_pdf(path, collection)
            else:
                result = ingest_html(path, collection)
        except Exception as e:
            print(f"  -> Unhandled error ingesting {path.name}: {e}")
            result = {"chunks": 0, "asset_class": "Error"}
        results[path.name] = result
        total_chunks += result["chunks"]

    summary = {
        "docs_ingested": len(all_files),
        "total_chunks": total_chunks,
        "results": results,
    }

    invalidate_stats_cache()
    print(f"\nDone. {len(all_files)} documents, {total_chunks} total chunks indexed.")
    return summary


_stats_cache: dict | None = None

def invalidate_stats_cache() -> None:
    global _stats_cache
    _stats_cache = None


def get_collection_stats() -> dict:
    """
    Returns current stats and the list of unique documents and asset classes
    in the vector store. Used to populate UI filters.
    Results are cached at module level — call invalidate_stats_cache() after
    any ingest or clear operation to force a refresh.
    """
    global _stats_cache
    if _stats_cache is not None:
        return _stats_cache

    try:
        collection = get_collection()
        count = collection.count()
        if count == 0:
            return {"total_chunks": 0, "ready": False, "documents": [], "asset_classes": [], "doc_class_map": {}}

        # Fetch all metadata once to build the doc inventory and filter lists
        sample = collection.get(limit=count, include=["metadatas"])

        # Build a mapping of document -> asset_class for UI filtering
        doc_class_map = {}
        for m in sample["metadatas"]:
            src = m.get("source", "Unknown")
            cls = m.get("asset_class", "Unknown")
            doc_class_map[src] = cls

        # Apply manual overrides — they always win over auto-classification
        overrides = load_overrides()
        for doc, cls in overrides.items():
            if doc in doc_class_map:
                doc_class_map[doc] = cls

        docs = sorted(doc_class_map.keys())
        classes = sorted(set(doc_class_map.values()))

        _stats_cache = {
            "total_chunks": count,
            "ready": True,
            "documents": docs,
            "asset_classes": classes,
            "doc_class_map": doc_class_map,
        }
        return _stats_cache
    except Exception as e:
        print(f"Warning: get_collection_stats() failed: {e}")
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
