"""
corpus_expand.py — Automated Corpus Expansion via SEC EDGAR
------------------------------------------------------------
Downloads 20-30 public institutional investment documents from EDGAR
into data/raw_pdfs/, covering:
  - Major mutual fund N-CSR filings (shareholder reports)
  - Major institutional 13F-HR filings (portfolio holdings)
  - Investment advisor ADV filings
  - Asset manager 10-K annual reports

Run from the project root:
    python corpus_expand.py

After completion, click "Ingest Documents" in the Streamlit UI (or run
python ingest.py) to embed everything into ChromaDB.
"""

import re
import sys
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# Re-use sourcing helpers
from sourcing import (
    EFTS_SEARCH_URL, EDGAR_ARCHIVES, HEADERS,
    search_edgar, get_filing_pdfs, download_pdf,
)

RAW_PDF_DIR = Path(__file__).resolve().parent / "data" / "raw_pdfs"
RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Target corpus — 30 documents across 4 categories
# ---------------------------------------------------------------------------
# Format: (search_query, form_type, description)
# We take the FIRST (most recent) search result for each.

TARGETS = [
    # ── Mutual fund shareholder reports (N-CSR) ──────────────────────────────
    ("Vanguard 500 Index Fund",                    "N-CSR",  "Vanguard 500 Index N-CSR"),
    ("Vanguard Total Bond Market Index Fund",       "N-CSR",  "Vanguard Total Bond N-CSR"),
    ("Vanguard International Growth Fund",          "N-CSR",  "Vanguard Intl Growth N-CSR"),
    ("Vanguard Total World Stock Index Fund",       "N-CSR",  "Vanguard Total World N-CSR"),
    ("Vanguard LifeStrategy Growth Fund",           "N-CSR",  "Vanguard LifeStrategy N-CSR"),
    ("Vanguard Target Retirement 2030",             "N-CSR",  "Vanguard Target 2030 N-CSR"),
    ("PIMCO Income Fund",                           "N-CSR",  "PIMCO Income N-CSR"),
    ("PIMCO Total Return Fund",                     "N-CSR",  "PIMCO Total Return N-CSR"),
    ("BlackRock Global Allocation Fund",            "N-CSR",  "BlackRock Global Allocation N-CSR"),
    ("T. Rowe Price Blue Chip Growth Fund",         "N-CSR",  "T Rowe Blue Chip N-CSR"),
    ("T. Rowe Price Growth Stock Fund",             "N-CSR",  "T Rowe Growth Stock N-CSR"),
    ("Fidelity Contrafund",                         "N-CSR",  "Fidelity Contrafund N-CSR"),
    ("Fidelity 500 Index Fund",                     "N-CSR",  "Fidelity 500 Index N-CSR"),
    ("American Funds Growth Fund of America",       "N-CSR",  "American Funds Growth N-CSR"),
    ("Dodge Cox Stock Fund",                        "N-CSR",  "Dodge Cox Stock N-CSR"),

    # ── Institutional holdings (13F-HR) ──────────────────────────────────────
    ("BlackRock Inc",                               "13F-HR", "BlackRock 13F Holdings"),
    ("Vanguard Group",                              "13F-HR", "Vanguard 13F Holdings"),
    ("State Street Corporation",                    "13F-HR", "State Street 13F Holdings"),
    ("T. Rowe Price Associates",                    "13F-HR", "T Rowe Price 13F Holdings"),
    ("Wellington Management",                       "13F-HR", "Wellington 13F Holdings"),

    # ── Investment advisor registrations (ADV) ────────────────────────────────
    ("PIMCO",                                       "ADV",    "PIMCO ADV Registration"),
    ("Dodge Cox",                                   "ADV",    "Dodge Cox ADV Registration"),
    ("Dimensional Fund Advisors",                   "ADV",    "DFA ADV Registration"),
    ("Causeway Capital Management",                 "ADV",    "Causeway ADV Registration"),
    ("Artisan Partners",                            "ADV",    "Artisan Partners ADV Registration"),

    # ── Public company 10-K (asset managers) ─────────────────────────────────
    ("BlackRock Inc",                               "10-K",   "BlackRock 10-K Annual Report"),
    ("T. Rowe Price Group",                         "10-K",   "T Rowe Price 10-K Annual Report"),
    ("Franklin Resources",                          "10-K",   "Franklin Resources 10-K"),
    ("Invesco Ltd",                                 "10-K",   "Invesco 10-K Annual Report"),
    ("Affiliated Managers Group",                   "10-K",   "AMG 10-K Annual Report"),
]


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    """Convert a description + extension to a safe filename."""
    safe = re.sub(r"[^\w\s-]", "", name).strip()
    safe = re.sub(r"\s+", "_", safe)
    return safe[:80]


def _find_main_doc(docs: list[dict]) -> dict | None:
    """
    From a list of filing docs, pick the best one to download.
    Priority: largest PDF > largest HTML (ignore index/exhibit files).
    """
    if not docs or (len(docs) == 1 and "error" in docs[0]):
        return None

    real_docs = [d for d in docs if "error" not in d]
    if not real_docs:
        return None

    # PDFs first (rare but preferred), then HTML sorted largest first
    pdfs  = [d for d in real_docs if d["doc_type"] == "PDF"]
    htmls = [d for d in real_docs if d["doc_type"] == "HTML"]

    def size_val(d):
        s = d.get("size_kb", 0)
        return s if isinstance(s, (int, float)) else 0

    if pdfs:
        return max(pdfs, key=size_val)
    if htmls:
        return max(htmls, key=size_val)
    return None


def download_one(search_query: str, form_type: str, description: str) -> dict:
    """
    Finds and downloads one EDGAR filing matching the query + form_type.
    Returns a result dict: {description, status, filename, chunks_hint}
    """
    print(f"\n  Searching: '{search_query}' [{form_type}]")

    # Search EDGAR
    results = search_edgar(search_query, [form_type], max_results=3)

    if isinstance(results, dict) and "error" in results:
        return {"description": description, "status": "search_error", "detail": results["error"]}
    if not results:
        return {"description": description, "status": "not_found"}

    filing = results[0]
    print(f"  Found: {filing['entity']} | {filing['form_type']} | {filing['date']}")

    # Get documents list
    docs = get_filing_pdfs(filing["cik"], filing["accession"])
    main_doc = _find_main_doc(docs)

    if not main_doc:
        return {"description": description, "status": "no_document",
                "detail": f"No downloadable doc in accession {filing['accession']}"}

    # Build filename from the actual entity EDGAR returned (more accurate than
    # the search description when EDGAR's text search returns a related entity)
    ext = Path(main_doc["name"]).suffix.lower()

    # Use the actual entity name from EDGAR as the filename base — more accurate
    # than the search description when EDGAR returns a related-but-different entity
    entity_slug = re.sub(r"[^\w\s-]", "", filing["entity"]).strip()
    entity_slug = re.sub(r"\s+", "_", entity_slug)[:60]
    form_slug   = form_type.replace("-", "")
    filename    = f"{entity_slug}_{form_slug}{ext}"

    dest = RAW_PDF_DIR / filename
    if dest.exists():
        print(f"  Already exists: {filename}")
        return {"description": description, "status": "already_exists", "filename": filename}

    # Download — pass filing metadata so a .meta.json sidecar is written
    # alongside the file, enabling ingest.py to attach rich chunk metadata
    # without re-querying EDGAR or firing an LLM extraction call.
    print(f"  Downloading: {main_doc['name']} ({main_doc['size_kb']} KB) -> {filename}")
    result = download_pdf(main_doc["url"], filename, filing_meta=filing)

    if result["success"]:
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  Saved: {filename} ({size_mb:.1f} MB)")
        return {"description": description, "status": "downloaded", "filename": filename,
                "size_mb": round(size_mb, 1)}
    else:
        return {"description": description, "status": "download_error", "detail": result["error"]}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 65)
    print("CapitalContext - Corpus Expansion")
    print(f"Target: {len(TARGETS)} documents")
    print(f"Destination: {RAW_PDF_DIR}")
    print("=" * 65)

    results = []
    for i, (query, form, desc) in enumerate(TARGETS, 1):
        print(f"\n[{i}/{len(TARGETS)}] {desc}")
        result = download_one(query, form, desc)
        results.append(result)
        time.sleep(0.5)   # courteous pacing — well under EDGAR's 10 req/s limit

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("SUMMARY")
    print("=" * 65)

    downloaded   = [r for r in results if r["status"] == "downloaded"]
    already_had  = [r for r in results if r["status"] == "already_exists"]
    not_found    = [r for r in results if r["status"] == "not_found"]
    errors       = [r for r in results if r["status"] in ("search_error", "no_document", "download_error")]

    print(f"\nDownloaded:    {len(downloaded)}")
    print(f"Already had:   {len(already_had)}")
    print(f"Not found:     {len(not_found)}")
    print(f"Errors:        {len(errors)}")

    if downloaded:
        print("\nNew files:")
        for r in downloaded:
            print(f"  + {r['filename']}  ({r.get('size_mb', '?')} MB)")

    if not_found:
        print("\nNot found on EDGAR (search returned no hits):")
        for r in not_found:
            print(f"  - {r['description']}")

    if errors:
        print("\nErrors:")
        for r in errors:
            print(f"  ! {r['description']}: {r.get('detail', r['status'])}")

    total_in_dir = len(list(RAW_PDF_DIR.glob("*.pdf")) + list(RAW_PDF_DIR.glob("*.htm")) + list(RAW_PDF_DIR.glob("*.html")))
    print(f"\nTotal documents in data/raw_pdfs/: {total_in_dir}")
    print("\nNext step: click 'Ingest Documents' in the Streamlit UI")
    print("  or run:  python ingest.py")
    print("=" * 65)


if __name__ == "__main__":
    main()
