"""
sourcing.py — Automated Document Sourcing via SEC EDGAR
--------------------------------------------------------
Searches the SEC's EDGAR database for public institutional documents
by fund name or ticker, and downloads PDFs directly to data/raw_pdfs/.

EDGAR is a free public API — no key required. The SEC does require a
User-Agent header identifying the application (fair access policy).
Rate limit: max 10 requests/second. Small delays are added per request.

Supported filing types:
    N-CSR   — Annual/semi-annual fund shareholder report
    485BPOS — Prospectus (strategy, mandate, fees)
    ADV     — Investment advisor registration
    10-K    — Annual report (public companies)

EDGAR EFTS response field reference (actual _source keys):
    display_names   — list: ["VANGUARD 500 INDEX FUND  (CIK 0000036405)"]
    form            — filing type: "N-CSR"
    adsh            — accession number: "0000932471-24-023456"
    ciks            — list: ["0000036405"]
    period_ending   — period of report: "2024-09-30"
    file_date       — filing date: "2024-11-27"
"""

import re
import time
import requests
from pathlib import Path

# --- Config ------------------------------------------------------------------

RAW_PDF_DIR = Path(__file__).resolve().parent / "data" / "raw_pdfs"

EFTS_SEARCH_URL  = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVES   = "https://www.sec.gov/Archives/edgar/data"

# SEC fair access policy requires identifying the application in User-Agent
HEADERS = {"User-Agent": "CapitalContext/1.0 research@capitalcontext.local"}

# Filing types available in the UI
FORM_TYPES = {
    "N-CSR":    "Annual/Semi-Annual Fund Report",
    "485BPOS":  "Prospectus",
    "ADV":      "Investment Advisor Registration",
    "10-K":     "Annual Report (Public Co.)",
    "10-Q":     "Quarterly Report (Public Co.)",
    "13F-HR":   "Institutional Holdings Report",
}


# --- Step 1: Search EDGAR ----------------------------------------------------

def search_edgar(query: str, form_types: list, max_results: int = 8) -> list | dict:
    """
    Searches EDGAR's full-text search index for filings matching the query.

    Uses the EFTS (EDGAR Full-Text Search) API which returns JSON.
    Fetches a wider candidate set (20), sorts by date in Python, returns
    the most recent max_results filings. EDGAR's server-side sort is
    unreliable and can trigger 500 errors, so we sort client-side.

    Returns a list of filing dicts, or a dict with an 'error' key on failure.

    Each result includes:
        entity      — fund or company name
        form_type   — N-CSR, 485BPOS, etc.
        description — human-readable form type label
        date        — filing date
        period      — period the filing covers
        accession   — accession number (used to fetch documents)
        cik         — SEC Central Index Key (used to build filing URLs)
    """
    params = {
        "q":         f'"{query}"',
        "forms":     ",".join(form_types),
        "dateRange": "custom",
        "startdt":   "2022-01-01",   # last ~4 years of filings
        "enddt":     "2026-12-31",   # required: EDGAR ignores startdt without enddt
    }

    # EDGAR EFTS occasionally returns 500 on transient overload — retry once
    resp = None
    for attempt in range(2):
        try:
            resp = requests.get(
                EFTS_SEARCH_URL,
                params=params,
                headers=HEADERS,
                timeout=15,
            )
            if resp.status_code != 500:
                break
            time.sleep(1.5)   # brief back-off before retry
        except requests.RequestException as e:
            return {"error": f"EDGAR search failed: {e}"}

    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "N/A"
        return {"error": f"EDGAR search failed (HTTP {status}). EDGAR may be temporarily unavailable — please try again in a moment."}

    # Fetch up to 20 candidates so we can sort by date client-side
    # (EDGAR's server-side date sort triggers 500 errors)
    hits = resp.json().get("hits", {}).get("hits", [])[:20]

    if not hits:
        return []

    results = []
    for hit in hits:
        src = hit.get("_source", {})

        # Entity name: display_names is a list like
        # ["VANGUARD 500 INDEX FUND  (CIK 0000036405)"]
        display_names = src.get("display_names", [])
        raw_name = display_names[0] if display_names else "Unknown"
        # Strip the " (CIK XXXXXXXXXX)" suffix EDGAR appends, then normalize whitespace
        clean_name = re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", raw_name).strip()
        clean_name = re.sub(r"\s{2,}", " ", clean_name)  # collapse double spaces
        entity_name = clean_name.title()

        # CIK: stored as list ["0000036405"] — strip leading zeros for URL construction
        ciks = src.get("ciks", [])
        cik_raw = ciks[0] if ciks else ""
        try:
            cik = str(int(cik_raw))
        except (ValueError, TypeError):
            cik = cik_raw

        form = src.get("form", "")

        results.append({
            "entity":      entity_name,
            "form_type":   form,
            "description": FORM_TYPES.get(form, form),
            "date":        src.get("file_date", ""),
            "period":      src.get("period_ending") or "N/A",
            "accession":   src.get("adsh", ""),
            "cik":         cik,
        })

    # Sort most-recent first (EDGAR's server-side sort is unreliable)
    results.sort(key=lambda r: r["date"], reverse=True)
    return results[:max_results]


# --- Step 2: Get PDFs from a filing ------------------------------------------

def get_filing_pdfs(cik: str, accession: str) -> list:
    """
    Fetches the filing index for a specific EDGAR submission and returns
    a list of PDF files found within it.

    EDGAR stores every filing in a folder named by the accession number
    (dashes removed). The index JSON lists all documents in that folder.

    accession format in:  "0000932471-24-023456"  (with dashes, from search)
    accession folder:     "000093247124023456"     (dashes removed, for URL)

    Returns a list of dicts with 'name' and 'url' for each PDF found.
    Returns an empty list if the index cannot be fetched.
    """
    accession_nodash = accession.replace("-", "")
    # EDGAR filing index: the correct JSON path is just /index.json
    # (not /{accession}-index.json which does not exist)
    index_url = f"{EDGAR_ARCHIVES}/{cik}/{accession_nodash}/index.json"

    try:
        resp = requests.get(index_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("directory", {}).get("item", [])
    except requests.RequestException as e:
        print(f"EDGAR filing index fetch failed ({index_url}): {e}")
        return [{"error": f"Could not reach EDGAR: {e}"}]
    except (ValueError, KeyError) as e:
        print(f"EDGAR filing index parse error ({index_url}): {e}")
        return [{"error": f"Malformed EDGAR response: {e}"}]

    docs = []
    for item in items:
        name = item.get("name", "")
        name_lower = name.lower()

        # Skip index / header / image / stylesheet files
        if any(x in name_lower for x in ("index", "header")) or name_lower.endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".css", ".js", ".txt", ".xml")
        ):
            continue

        size_str = str(item.get("size", ""))
        size_kb = round(int(size_str) / 1024, 1) if size_str.isdigit() else "?"

        if name_lower.endswith(".pdf"):
            docs.append({
                "name":     name,
                "url":      f"{EDGAR_ARCHIVES}/{cik}/{accession_nodash}/{name}",
                "size_kb":  size_kb,
                "doc_type": "PDF",
            })
        elif name_lower.endswith((".htm", ".html")):
            docs.append({
                "name":     name,
                "url":      f"{EDGAR_ARCHIVES}/{cik}/{accession_nodash}/{name}",
                "size_kb":  size_kb,
                "doc_type": "HTML",
            })

    # PDFs first (rare but preferred), then HTML sorted largest-first
    docs.sort(key=lambda d: (0 if d["doc_type"] == "PDF" else 1,
                              -(d["size_kb"] if isinstance(d["size_kb"], float) else 0)))

    time.sleep(0.15)  # courtesy delay — EDGAR rate limit is 10 req/sec
    return docs


# --- Step 3: Download a PDF --------------------------------------------------

def download_pdf(url: str, filename: str, filing_meta: dict | None = None) -> dict:
    """
    Downloads a PDF or HTML filing from an EDGAR URL to data/raw_pdfs/.

    If filing_meta is provided (a dict from search_edgar results), writes a
    companion .meta.json sidecar next to the downloaded file so ingestion can
    attach human-readable company name, filing type, and period to every chunk
    without re-querying EDGAR.

    Streams the response in chunks to handle large documents efficiently.
    Returns a result dict with success status and path or error message.

    The 0.15s delay after download keeps us well under EDGAR's rate limit.
    """
    import json as _json

    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_PDF_DIR / filename

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            stream=True,
            timeout=60,
        )
        resp.raise_for_status()

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Write sidecar metadata so ingest.py can attach rich fields to chunks.
        if filing_meta:
            company  = filing_meta.get("entity", "")
            form     = filing_meta.get("form_type", "")
            period   = filing_meta.get("period", "") or ""
            filed    = filing_meta.get("date", "")
            # Format: "Pimco Funds — N-CSR (2025-11-30)"
            period_part = f" ({period})" if period and period != "N/A" else ""
            source_label = f"{company} — {form}{period_part}".strip(" —")
            sidecar = {
                "company_name": company,
                "filing_type":  form,
                "period":       period,
                "filed_date":   filed,
                "source_label": source_label,
            }
            sidecar_path = dest.with_suffix("").with_suffix("") \
                if dest.suffix.lower() in (".htm", ".html") \
                else dest.with_suffix("")
            # Handle double extension (.meta.json) cleanly regardless of .htm/.html/.pdf
            stem = Path(filename).stem
            (RAW_PDF_DIR / f"{stem}.meta.json").write_text(
                _json.dumps(sidecar, indent=2), encoding="utf-8"
            )

        time.sleep(0.15)
        return {"success": True, "path": str(dest), "filename": filename}

    except Exception as e:
        return {"success": False, "error": str(e), "filename": filename}
