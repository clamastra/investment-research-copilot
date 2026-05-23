# CapitalContext
**Institutional Investment Document Intelligence System**

A local retrieval-augmented generation (RAG) pipeline for institutional investment research workflows. Ingests public investment documents, retrieves semantically relevant passages, and generates source-grounded research outputs with citations.

Built as an enterprise AI portfolio piece targeting AI/data consulting roles at the intersection of finance and enterprise AI.

---

## Positioning

**This is not:** a chatbot, a hobby project, or a prompt engineering demo.

**This is:** an enterprise document intelligence system demonstrating retrieval-augmented generation, vector search, metadata indexing, semantic retrieval, and governance-aware AI architecture — applied to institutional investment workflows.

**Interview pitch:**
> "I designed a retrieval-augmented document intelligence system for institutional investment workflows using vector search, metadata indexing, semantic retrieval, and governance-aware AI outputs."

---

## Architecture

```
Public PDFs
  → PyMuPDF          (extract raw text from PDFs)
  → Chunking         (split text into overlapping passages)
  → Embeddings       (convert chunks to vectors via Anthropic API)
  → ChromaDB         (store vectors + metadata locally on disk)
  → Streamlit UI     (user enters query, selects output mode)
  → Semantic search  (query is embedded, ChromaDB finds closest chunks)
  → Claude API       (retrieved chunks + query → grounded response)
  → Structured output (Q&A with citations, IC memo, risk summary, manager comparison)
```

**Why local:** Governance constraint — no proprietary data leaves the machine. The only external calls are to the Anthropic API, which operates on public documents only.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python |
| UI | Streamlit |
| Vector database | ChromaDB |
| LLM | Anthropic Claude API |
| PDF extraction | PyMuPDF |
| Environment | python-dotenv |
| Data | pandas |

---

## Key Concepts

**Embeddings:** Text converted into vectors (lists of numbers) that capture meaning. Similar meaning = mathematically similar vectors. This enables semantic search — finding relevant passages by meaning, not keyword matching.

**Vector database (ChromaDB):** A database designed to store and search vectors by similarity. Unlike SQL (exact match), ChromaDB finds the closest semantic matches to a query. Stores vectors alongside metadata (document name, page number, date) to enable citations.

**RAG (Retrieval-Augmented Generation):** Instead of asking an LLM to answer from memory (which causes hallucination), RAG retrieves relevant source passages first, then asks the LLM to answer using only those passages. This grounds responses in real documents and enables citations.

**Streamlit:** Python library that generates an interactive web UI without HTML/CSS/JavaScript. Handles the file uploader, query input, output mode selector, and response display.

---

## Output Modes

| Mode | Description |
|---|---|
| Q&A with citations | Source-grounded answers citing document and page |
| IC Memo draft | Structured investment committee memo with sections |
| Risk summary | Risks categorized by type (market, liquidity, operational, etc.) |
| Manager comparison | Side-by-side comparison table of strategies, fees, risk profiles |

---

## Target Documents

- Pension annual reports
- Investment policy statements (IPS)
- Manager letters
- SEC filings (ADV Part 2)
- Consultant reports
- Macro outlook PDFs
- Public DDQs (due diligence questionnaires)
- Operational due diligence (ODD) documents
- Asset manager strategy docs

---

## Project Structure

```
investment-research-copilot/
├── app.py              # Streamlit UI
├── ingest.py           # PDF ingestion pipeline (Week 2)
├── rag.py              # Retrieval + response generation (Week 2-3)
├── prompts.py          # Prompt templates for all output modes
├── requirements.txt    # Python dependencies
├── .env.example        # API key template (copy to .env)
├── .gitignore
├── data/
│   ├── raw_pdfs/       # Source PDFs (excluded from GitHub)
│   └── processed/      # Processed text (excluded from GitHub)
├── vector_store/       # ChromaDB database (excluded from GitHub)
└── screenshots/        # UI screenshots for portfolio (excluded from GitHub)
```

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
# Open .env and replace the placeholder with your real key:
# ANTHROPIC_API_KEY=sk-ant-...

# Run the app
streamlit run app.py
```

---

## Build Progress

### ✅ Week 1 — Scaffold (Complete)
- [x] GitHub repo created
- [x] Python virtual environment configured
- [x] Core dependencies installed (Streamlit, Anthropic, ChromaDB, PyMuPDF, sentence-transformers)
- [x] Folder structure established
- [x] Working Streamlit UI shell
- [x] Prompt templates written for all 4 output modes
- [x] `.gitignore` configured (API keys and data excluded)
- [x] Initial commit pushed to GitHub

### ✅ Week 2 — Ingestion Pipeline (Complete)
- [x] PDF text extraction with PyMuPDF (page by page, blank pages skipped)
- [x] Text chunking with overlap (1,500 char chunks, 150 char overlap)
- [x] Metadata assignment per chunk (source name, page number, filename)
- [x] Local embeddings via sentence-transformers (all-MiniLM-L6-v2, runs on device)
- [x] ChromaDB setup with cosine similarity and persistent disk storage
- [x] Ingestion tested against 4 Vanguard PDFs — 1,011 chunks indexed
- [x] Ingest button wired into Streamlit UI

### ✅ Week 3 — RAG Pipeline (Complete)
- [x] Semantic retrieval from ChromaDB with 10-candidate wider net
- [x] Distance threshold filtering (0.7) — removes low-relevance chunks before generation
- [x] Citation format: [Document Name | Page N] — no ambiguous numbered sources
- [x] Claude API integration (claude-haiku-4-5-20251001, configurable)
- [x] Hallucination controls — sources-only prompts + explicit gap disclosure
- [x] All 4 output modes tested end-to-end against real Vanguard documents
- [x] Retrieval failure mode documented: vocabulary mismatch, query expansion flagged as next improvement

### ✅ Week 4 — Structured Outputs (Complete ahead of schedule)
- [x] IC Memo drafting — full structured memo with Executive Summary, Key Risks, Manager Assessment, Recommendation
- [x] Risk summary — categorized by Market, Liquidity, Operational, Counterparty, Regulatory risk
- [x] Manager comparison — structured table with explicit data gap disclosure
- [x] Fee structure extraction — surfaced via Q&A and comparison modes

### ⬜ Week 5 — Polish
- [ ] UI refinement
- [ ] Error handling
- [ ] Governance framework documentation
- [ ] README finalization
- [ ] Screenshots

### ⬜ Week 6 — Interview Prep
- [ ] Architecture diagram
- [ ] Resume bullets
- [ ] Demo preparation
- [ ] GitHub cleanup

---

## Data Policy

- Public documents and synthetic datasets only
- No employer proprietary information
- Local execution — data stays on machine
- Personal API keys only
- Governance-first design

---

## Estimated Cost

| Item | Cost |
|---|---|
| Python, Git, VSCode, ChromaDB, Streamlit | $0 |
| GitHub | $0 |
| Anthropic API usage (estimated) | $20–100 total |
| **Total** | **< $100** |
