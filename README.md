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
# Edit .env and add your Anthropic API key

# Run the app
streamlit run app.py
```

---

## Build Progress

### ✅ Week 1 — Scaffold (Complete)
- [x] GitHub repo created
- [x] Python virtual environment configured
- [x] Core dependencies installed (Streamlit, Anthropic, ChromaDB, PyMuPDF)
- [x] Folder structure established
- [x] Working Streamlit UI shell
- [x] Prompt templates written for all 4 output modes
- [x] `.gitignore` configured (API keys and data excluded)
- [x] Initial commit pushed to GitHub

### 🔄 Week 2 — Ingestion Pipeline (Next)
- [ ] PDF text extraction with PyMuPDF
- [ ] Text chunking with overlap
- [ ] Metadata assignment (document name, page, date)
- [ ] Embedding generation via Anthropic API
- [ ] ChromaDB setup and indexing
- [ ] Retrieval testing

### ⬜ Week 3 — RAG Pipeline
- [ ] Semantic retrieval from ChromaDB
- [ ] Claude API integration
- [ ] Citation generation
- [ ] Hallucination controls
- [ ] Q&A output mode

### ⬜ Week 4 — Structured Outputs
- [ ] IC Memo drafting
- [ ] Risk summary generation
- [ ] Manager comparison tables
- [ ] Fee structure extraction

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
