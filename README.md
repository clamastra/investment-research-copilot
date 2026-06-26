# CapitalContext
**Institutional Investment Document Intelligence System**

A local retrieval-augmented generation (RAG) pipeline for institutional investment research workflows. Ingests public SEC filings and investment documents from EDGAR, retrieves semantically relevant passages, and generates source-grounded research outputs with citations.

Accessible remotely via email — send a query from any device, receive a formatted research brief back in minutes.

Built as an enterprise AI portfolio piece targeting AI/data consulting roles at the intersection of finance and enterprise AI.

---

## Positioning

**This is not:** a chatbot, a hobby project, or a prompt engineering demo.

**This is:** an enterprise document intelligence system demonstrating retrieval-augmented generation, vector search, metadata indexing, semantic retrieval, SEC EDGAR integration, and governance-aware AI architecture — applied to institutional investment workflows.

**Interview pitch:**
> "I designed a retrieval-augmented document intelligence system for institutional investment workflows using vector search, metadata indexing, semantic retrieval, and governance-aware AI outputs — with automated SEC EDGAR corpus expansion and a remote email interface."

---

## Architecture

```
SEC EDGAR API
  → sourcing.py      (search filings by form type + entity, download HTML/PDF)
  → corpus_expand.py (30-target batch downloader — N-CSR, 10-K, 13F-HR)

Local Documents
  → PyMuPDF / HTMLParser  (extract raw text from PDFs and iXBRL HTML filings)
  → Chunking               (1,500-char chunks, 150-char overlap)
  → sentence-transformers  (embed chunks locally via all-MiniLM-L6-v2)
  → ChromaDB               (store vectors + metadata on disk, cosine similarity)

Query Path
  → Streamlit UI     (query entry, output mode selector, document inventory)
  → Semantic search  (top-10 chunks retrieved, distance-filtered at 0.7)
  → Claude API       (retrieved chunks + query → grounded response)
  → Structured output

Email Interface
  → Gmail IMAP poll  (every 5 min, checks dedicated inbox)
  → Router           (RESEARCH: ticker → agentic assistant | QUERY: → RAG)
  → Gmail SMTP       (sends HTML-formatted response back to sender)
```

**Why local:** Governance constraint — no proprietary data leaves the machine. The only external calls are to the Anthropic API (public documents only) and SEC EDGAR (public filings only).

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| Vector database | ChromaDB (persistent, cosine similarity) |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2, runs on device) |
| LLM | Anthropic Claude API |
| PDF extraction | PyMuPDF |
| HTML/iXBRL extraction | stdlib HTMLParser (custom iXBRL-aware subclass) |
| SEC EDGAR | EDGAR EFTS full-text search + filing index API |
| Email | imaplib + smtplib (Gmail IMAP/SMTP) |
| HTTP | requests |
| Environment | python-dotenv |
| Testing | pytest |

---

## Key Concepts

**Embeddings:** Text converted into vectors (lists of numbers) that capture meaning. Similar meaning = mathematically similar vectors. This enables semantic search — finding relevant passages by meaning, not keyword matching.

**Vector database (ChromaDB):** A database designed to store and search vectors by similarity. Unlike SQL (exact match), ChromaDB finds the closest semantic matches to a query. Stores vectors alongside metadata (document name, page number, asset class) to enable citations.

**RAG (Retrieval-Augmented Generation):** Instead of asking an LLM to answer from memory (which causes hallucination), RAG retrieves relevant source passages first, then asks the LLM to answer using only those passages. This grounds responses in real documents and enables citations.

**iXBRL:** SEC filings after ~2021 are formatted in iXBRL (Inline eXtensible Business Reporting Language) — HTML mixed with XML namespace tags (`ix:*`, `xbrli:*`). These namespace-prefixed elements contain machine-readable metadata, not human-readable text. The custom HTMLParser subclass skips all namespaced elements entirely.

---

## Output Modes

| Mode | Description |
|---|---|
| Q&A with citations | Source-grounded answers citing document and page |
| IC Memo draft | Structured investment committee memo (Executive Summary, Key Risks, Manager Assessment, Recommendation) |
| Risk summary | Risks categorized by type (market, liquidity, operational, counterparty, regulatory) |
| Manager comparison | Side-by-side table of strategies, fees, risk profiles with explicit data-gap disclosure |

---

## EDGAR Integration

CapitalContext can search and download public SEC filings directly from EDGAR.

**Supported form types:**

| Form | Description |
|---|---|
| N-CSR | Mutual fund certified shareholder report (semi-annual) |
| 485BPOS | Fund prospectus (post-effective amendment) |
| ADV | Investment adviser registration (Part 2 — narrative disclosures) |
| 10-K | Annual report (public companies) |
| 10-Q | Quarterly report |
| 13F-HR | Quarterly institutional holdings report |

**How it works:**

1. `sourcing.py` — `search_edgar(query, form_type)` queries the EDGAR full-text search API and returns matching filings with metadata (entity, date, accession number). `get_filing_pdfs(accession_nodash)` fetches the filing index and returns downloadable document links, sorted by size. `download_pdf(url, filename)` saves files to `data/raw_pdfs/`.

2. **Streamlit "Find PDFs" tab** — enter a company name and form type, browse results, and download with one click.

3. `corpus_expand.py` — batch downloader targeting 30 specific filings across major asset managers (Vanguard, PIMCO, T. Rowe Price, BlackRock, Dodge & Cox, Fidelity). Run once to populate the corpus.

**Notes:**
- EDGAR returns nearest-match results, not exact matches — verify entity names in downloaded filenames.
- ADV form type is not reliably indexed by EDGAR's full-text search system (returns no hits for most advisers). Download ADV Part 2 documents directly from the IAPD public disclosure site.
- 13F-HR filings are often submitted as XML (not HTML/PDF) and may not have a downloadable document in the filing index.
- Large iXBRL files (PIMCO N-CSR: 101 MB, Lincoln Variable: 98 MB) may take 30–60 seconds to ingest.

---

## Email Interface

CapitalContext can be queried remotely from any device via email.

**Subject line format:**

| Subject | Routes to | Response |
|---|---|---|
| `RESEARCH: AAPL` | Agentic research assistant (multi-tool) | Full research brief in 1–3 min |
| `QUERY: What are PIMCO's income risks?` | CapitalContext RAG | Source-grounded answer with citations |

Matching is case-insensitive. The polling script checks the inbox every 5 minutes and sends:
1. An immediate confirmation email
2. A full HTML-formatted response with metadata (elapsed time, estimated cost, token counts)

**Important:** Send requests from a personal Gmail or personal phone. Do **not** send from a work email — your firm's DLP (data loss prevention) system may flag or quarantine emails containing financial tickers or investment terms. See [email_interface/SETUP.md](email_interface/SETUP.md) for complete setup instructions.

**Requires:** home laptop running, tmux session active, Gmail App Password configured in `.env`.

---

## Project Structure

```
investment-research-copilot/
├── app.py                  # Streamlit UI
├── ingest.py               # Ingestion pipeline (PDF + iXBRL HTML)
├── rag.py                  # Retrieval + response generation
├── sourcing.py             # SEC EDGAR search and download
├── prompts.py              # Prompt templates for all output modes
├── corpus_expand.py        # 30-target EDGAR batch downloader
├── requirements.txt        # Python dependencies
├── .env.example            # Credential template (copy to .env)
├── .gitignore
│
├── email_interface/
│   ├── __init__.py
│   ├── config.py           # Credentials and constants
│   ├── router.py           # Subject parser + backend dispatch
│   ├── formatter.py        # Markdown-to-HTML email builder
│   ├── poll.py             # Gmail IMAP polling daemon
│   └── SETUP.md            # Step-by-step email interface setup
│
├── tests/
│   ├── conftest.py         # Shared pytest fixtures
│   ├── test_ingest.py      # Ingestion pipeline tests
│   ├── test_rag.py         # Retrieval and generation tests
│   ├── test_sourcing.py    # EDGAR integration tests
│   └── test_edge_cases.py  # Edge cases (empty corpus, API failures, etc.)
│
├── data/
│   ├── raw_pdfs/           # Source documents (excluded from GitHub)
│   └── processed/          # Processed text (excluded from GitHub)
├── vector_store/           # ChromaDB database (excluded from GitHub)
├── logs/                   # Email audit log JSONL (excluded from GitHub)
└── screenshots/            # UI screenshots (excluded from GitHub)
```

---

## Data Sources

The corpus contains 23 publicly available SEC filings downloaded from EDGAR, organized by asset class:

**Mutual Fund Shareholder Reports (N-CSR)**
- Fidelity Greenwood Street Trust N-CSR (12.4 MB)
- Aspiriant Trust N-CSR (2.5 MB)
- Augustar Variable Insurance Products Fund N-CSR (22.9 MB)
- Vanguard International Equity Index Funds N-CSR (39.1 MB)
- Vanguard Star Funds N-CSR (18.2 MB)
- Vanguard Chester Funds N-CSR (3.2 MB)
- PIMCO Funds N-CSR (101.1 MB)
- Lincoln Variable Insurance Products Trust N-CSR (98.4 MB)
- T. Rowe Price Blue Chip Growth Fund N-CSR (3.5 MB)
- T. Rowe Price Growth Stock Fund N-CSR (3.6 MB)
- Fidelity Contrafund N-CSR (6.6 MB)
- Fidelity Aberdeen Street Trust N-CSR (0.4 MB)
- Northern Lights Fund Trust N-CSR (5.0 MB)
- Dodge & Cox Funds N-CSR (13.8 MB)

**Annual Reports (10-K)**
- BlackRock Private Credit Fund 10-K (23.6 MB)
- T. Rowe Price Group 10-K (2.7 MB)
- Franklin Crypto Trust 10-K (1.5 MB)
- Invesco Galaxy Solana ETF 10-K (1.1 MB)
- Affiliated Managers Group 10-K (5.0 MB)

**Existing corpus (pre-expansion)**
- 4 Vanguard PDFs (fund fact sheets, strategy documents)

All documents are public filings retrieved from SEC EDGAR. No proprietary or employer data.

---

## Setup

```bash
# Clone the repo
git clone https://github.com/clamastra/investment-research-copilot.git
cd investment-research-copilot

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Add your API key
cp .env.example .env
# Open .env and replace the placeholder with your Anthropic API key

# (Optional) Expand corpus from EDGAR
python corpus_expand.py

# Run the app
streamlit run app.py
```

**To run tests:**
```bash
pytest tests/ -v
```

**To set up the email interface:**
See [email_interface/SETUP.md](email_interface/SETUP.md).

---

## Build Progress

### ✅ Phase 1 — Scaffold
- [x] GitHub repo, venv, dependencies
- [x] Streamlit UI shell
- [x] Prompt templates for all 4 output modes
- [x] `.gitignore` (API keys, data, credentials excluded)

### ✅ Phase 2 — Ingestion Pipeline
- [x] PDF text extraction with PyMuPDF (page-by-page, blank pages skipped)
- [x] iXBRL HTML extraction — custom HTMLParser skips all namespace-prefixed elements
- [x] Text chunking with overlap (1,500 char chunks, 150 char overlap)
- [x] Local embeddings via sentence-transformers (all-MiniLM-L6-v2)
- [x] ChromaDB with cosine similarity and persistent disk storage
- [x] Auto-classification by asset class (LLM-based, with manual override)
- [x] Stats cache — `get_collection_stats()` fetched once, cached until next ingest

### ✅ Phase 3 — RAG Pipeline
- [x] Semantic retrieval (top-10 candidates, distance threshold 0.7)
- [x] Citation format: `[Document Name | Page N]`
- [x] Claude API integration (claude-haiku-4-5-20251001)
- [x] Hallucination controls — sources-only prompts + explicit gap disclosure
- [x] All 4 output modes tested end-to-end
- [x] ChromaDB n_results overflow guard (retries with n=1 when filtered set < n)

### ✅ Phase 4 — EDGAR Integration
- [x] EDGAR EFTS full-text search API (`search_edgar`)
- [x] Filing index download and doc selection (`get_filing_pdfs`)
- [x] Streamlit "Find PDFs" tab with one-click download
- [x] Form types: N-CSR, 485BPOS, ADV, 10-K, 10-Q, 13F-HR
- [x] Error sentinels propagated to UI (network, HTTP, JSON parse errors)

### ✅ Phase 5 — Corpus Expansion + Bug Fixes
- [x] `corpus_expand.py` — 30-target EDGAR batch downloader
- [x] 19 new documents downloaded (14 N-CSR, 5 10-K), 23 total in corpus
- [x] Critical bug fixes (iXBRL parser, duplicate ingest button, env var loading)
- [x] `requirements.txt` pinned with version ranges
- [x] Comprehensive pytest suite: 90 tests across ingest, rag, sourcing, edge cases

### ✅ Phase 6 — Email Interface
- [x] Gmail IMAP polling daemon (`email_interface/poll.py`)
- [x] Subject-line router: `RESEARCH:` → agentic assistant, `QUERY:` → RAG
- [x] HTML email formatter with source citation table
- [x] Immediate confirmation email + full response email
- [x] JSONL audit log (`logs/email_requests.jsonl`)
- [x] Setup instructions with DLP warning (`email_interface/SETUP.md`)

### ⬜ Phase 7 — Polish
- [ ] Architecture diagram for portfolio
- [ ] Resume bullets
- [ ] Demo walkthrough script
- [ ] UI screenshots

---

## Known Limitations

| Limitation | Impact | Production Solution |
|---|---|---|
| **Text-only extraction** | Charts, graphs, and embedded images not ingested | Vision model to describe charts and extract table data |
| **Vocabulary mismatch** | Queries using different terminology may retrieve suboptimal chunks | Query expansion — LLM rewrites query into multiple phrasings before retrieval |
| **No hybrid search** | Semantic search only — exact keyword matching not supported | Combine vector search with BM25, merge results |
| **EDGAR nearest-match** | EDGAR EFTS returns closest match, not exact entity — downloaded file may be from a different fund family than searched | Use entity name from EDGAR response as filename; verify content after download |
| **ADV not indexed** | ADV form type returns no hits from EDGAR EFTS full-text search for most advisers | Download directly from IAPD public disclosure site |
| **13F-HR XML-only** | Many 13F filings are submitted as XML and have no downloadable HTML/PDF document | Parse XML directly using `xml.etree.ElementTree` |
| **Large iXBRL files** | Files >20 MB (PIMCO, Lincoln Variable) take 30–60 seconds to ingest | Stream-parse HTML rather than loading full file into memory |
| **Email latency** | Polling interval is 5 minutes — responses can take up to 5 min + processing time | Reduce to 60s interval, or use Gmail push notifications via PubSub |
| **Laptop dependency** | Email interface requires home laptop to be online and tmux session active | Deploy to cloud VM or containerize with Docker |
| **Classification edge cases** | Auto-classification uses filename + first 3 pages — may misclassify generic filenames | Manual override available in Document Inventory |

---

## Data Policy

- Public documents and public EDGAR filings only
- No employer proprietary information
- Local execution — document data stays on machine
- Only external calls: Anthropic API (query + public excerpts), SEC EDGAR (public filing metadata)
- Personal API keys only
- Gmail credentials stored in `.env` (gitignored)
- Governance-first design

---

## Estimated Cost

| Item | Cost |
|---|---|
| Python, Git, VSCode, ChromaDB, Streamlit | $0 |
| SEC EDGAR API | $0 (public) |
| GitHub | $0 |
| Anthropic API (estimated total) | $20–100 |
| **Total** | **< $100** |
