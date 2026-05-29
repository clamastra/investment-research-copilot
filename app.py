import streamlit as st
from ingest import ingest_all, get_collection_stats, save_override, ASSET_CLASSES
from rag import query as rag_query

# --- Page config -------------------------------------------------------------

st.set_page_config(
    page_title="CapitalContext",
    page_icon="📄",
    layout="wide",
)

# --- Asset class badge colors ------------------------------------------------

ASSET_CLASS_COLORS = {
    "US Equity":                "#1B6CA8",
    "International Equity":     "#2E8B57",
    "Fixed Income":             "#B8860B",
    "Multi-Asset":              "#6A0DAD",
    "Macro / Economic Outlook": "#1A7A7A",
    "ESG / CSR":                "#4A7C59",
    "Other":                    "#6B7280",
}

def badge(label: str) -> str:
    color = ASSET_CLASS_COLORS.get(label, "#6B7280")
    return (
        f'<span style="background-color:{color};color:white;padding:2px 10px;'
        f'border-radius:12px;font-size:0.75rem;font-weight:600;">{label}</span>'
    )

def scope_tag(label: str) -> str:
    return (
        f'<span style="background-color:#1B6CA8;color:white;padding:3px 12px;'
        f'border-radius:12px;font-size:0.8rem;font-weight:600;">🔍 {label}</span>'
    )

# --- Dark mode toggle --------------------------------------------------------

if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

# --- CSS ---------------------------------------------------------------------

def inject_css(dark: bool):
    if dark:
        bg        = "#141824"   # deep navy — easier on eyes than pure black
        sec_bg    = "#1C2333"   # slightly lighter navy
        input_bg  = "#1E2A3A"   # inputs and cards
        text      = "#DDE3EE"   # warm off-white — not harsh pure white
        subtext   = "#8892A4"   # muted blue-gray
        border    = "#2D3A4A"
        resp_bg   = "#1C2A3A"
        resp_bar  = "#4A90D9"
        metric_bg = "#1C2333"
    else:
        bg        = "#F0F4F8"   # very light blue-gray — softer than pure white
        sec_bg    = "#E2EAF4"
        input_bg  = "#FFFFFF"
        text      = "#1A202C"
        subtext   = "#4A5568"
        border    = "#C8D4E3"
        resp_bg   = "#E8EFF8"
        resp_bar  = "#1B6CA8"
        metric_bg = "#E2EAF4"

    st.markdown(f"""
    <style>
        /* ── Core app backgrounds ── */
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewBlockContainer"] {{
            background-color: {bg} !important;
        }}
        [data-testid="stHeader"] {{
            background-color: {bg} !important;
        }}
        .block-container {{
            padding-top: 1.2rem;
            background-color: {bg} !important;
        }}

        /* ── All text ── */
        .stApp p, .stApp span, .stApp div, .stApp label,
        .stApp h1, .stApp h2, .stApp h3, .stApp h4,
        .stMarkdown, .stMarkdown p, .stMarkdown li,
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stCaptionContainer"] p {{
            color: {text} !important;
        }}

        /* ── Widget labels ── */
        .stSelectbox label, .stTextArea label,
        .stToggle label, .stCheckbox label,
        .stMultiSelect label {{
            color: {text} !important;
        }}

        /* ── Inputs ── */
        .stTextArea textarea,
        .stSelectbox > div > div,
        .stMultiSelect > div > div {{
            background-color: {input_bg} !important;
            color: {text} !important;
            border-color: {border} !important;
        }}

        /* ── Placeholder text ── */
        .stTextArea textarea::placeholder {{
            color: {subtext} !important;
            opacity: 1 !important;
        }}

        /* ── Selectbox dropdown options ── */
        [data-baseweb="select"] *, [data-baseweb="popover"] * {{
            background-color: {input_bg} !important;
            color: {text} !important;
        }}

        /* ── Expanders ── */
        [data-testid="stExpander"],
        [data-testid="stExpander"] > div {{
            background-color: {sec_bg} !important;
            border-color: {border} !important;
        }}
        [data-testid="stExpander"] summary p {{
            color: {text} !important;
        }}

        /* ── Metrics ── */
        div[data-testid="stMetric"] {{
            background-color: {metric_bg} !important;
            border-radius: 8px;
            padding: 0.5rem 0.8rem;
        }}
        div[data-testid="stMetricValue"] > div {{ color: {text} !important; }}
        div[data-testid="stMetricLabel"] > div {{ color: {subtext} !important; }}

        /* ── Dividers ── */
        hr {{ border-color: {border} !important; }}

        /* ── Custom components ── */
        .response-box {{
            background-color: {resp_bg};
            border-left: 4px solid {resp_bar};
            border-radius: 6px;
            padding: 1.2rem 1.4rem;
            margin-top: 0.5rem;
            color: {text};
        }}
        .doc-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 0 4px 0;
            border-bottom: 1px solid {border};
        }}
        .doc-name {{
            font-size: 0.85rem;
            font-weight: 600;
            color: {text};
        }}
    </style>
    """, unsafe_allow_html=True)

inject_css(st.session_state.dark_mode)

# --- Header ------------------------------------------------------------------

hcol1, hcol2 = st.columns([5, 1])
with hcol1:
    st.markdown("## CapitalContext")
    st.caption("Institutional Investment Document Intelligence")
with hcol2:
    st.markdown("<br>", unsafe_allow_html=True)
    dark_toggle = st.toggle("Dark mode", value=st.session_state.dark_mode)
    if dark_toggle != st.session_state.dark_mode:
        st.session_state.dark_mode = dark_toggle
        st.rerun()

st.divider()

# --- Load stats --------------------------------------------------------------

stats = get_collection_stats()
doc_class_map = stats.get("doc_class_map", {})

# --- Layout ------------------------------------------------------------------

col1, col2 = st.columns([1, 2], gap="large")

# =============================================================================
# LEFT COLUMN
# =============================================================================

with col1:
    st.markdown("### Document Library")

    if stats["ready"]:
        m1, m2, m3 = st.columns(3)
        m1.metric("Documents", len(stats["documents"]))
        m2.metric("Chunks", stats["total_chunks"])
        m3.metric("Classes", len(stats["asset_classes"]))

        st.divider()

        # --- Scope filters first ---------------------------------------------
        st.markdown("**Scope**")
        asset_class_options = ["All Documents"] + stats["asset_classes"]
        selected_class = st.selectbox("Asset class", asset_class_options, label_visibility="collapsed")

        if selected_class == "All Documents":
            filtered_docs = stats["documents"]
        else:
            filtered_docs = [d for d, c in doc_class_map.items() if c == selected_class]

        selected_doc = st.selectbox(
            "Document",
            ["All Documents"] + sorted(filtered_docs),
            label_visibility="collapsed",
        )

        st.divider()

        # --- Ingest button ---------------------------------------------------
        if st.button("⟳  Ingest Documents", type="primary", use_container_width=True):
            with st.spinner("Classifying and ingesting PDFs..."):
                summary = ingest_all(clear_first=True)
            if "error" in summary:
                st.error(summary["error"])
            else:
                st.success(f"{summary['docs_ingested']} docs — {summary['total_chunks']} chunks indexed")
                with st.expander("Ingestion details"):
                    for filename, res in summary["results"].items():
                        st.markdown(
                            f"**{filename}** — {res['chunks']} chunks &nbsp;" + badge(res["asset_class"]),
                            unsafe_allow_html=True,
                        )
                st.rerun()

        st.divider()

        # --- Compact document inventory --------------------------------------
        st.markdown("**Inventory**")

        rows_html = ""
        for doc, cls in sorted(doc_class_map.items()):
            rows_html += (
                f'<div class="doc-row">'
                f'<span class="doc-name">{doc}</span>'
                f'{badge(cls)}'
                f'</div>'
            )

        st.markdown(
            f'<div style="max-height:220px;overflow-y:auto;padding-right:4px;">{rows_html}</div>',
            unsafe_allow_html=True,
        )

        # --- Single reclassify control ---------------------------------------
        with st.expander("Reclassify a document"):
            target_doc = st.selectbox("Document", sorted(doc_class_map.keys()), key="reclassify_doc")
            current_cls = doc_class_map.get(target_doc, "Other")
            new_cls = st.selectbox(
                "New asset class",
                ASSET_CLASSES,
                index=ASSET_CLASSES.index(current_cls) if current_cls in ASSET_CLASSES else len(ASSET_CLASSES) - 1,
                key="reclassify_cls",
            )
            if st.button("Apply", key="reclassify_apply"):
                save_override(target_doc, new_cls)
                st.toast(f"Reclassified → {new_cls}")
                st.rerun()

    else:
        st.info("No documents indexed. Drop PDFs into `data/raw_pdfs/` and click Ingest.")
        selected_class = "All Documents"
        selected_doc = "All Documents"

    if not stats["ready"]:
        st.divider()
        if st.button("⟳  Ingest Documents", type="primary", use_container_width=True):
            with st.spinner("Classifying and ingesting PDFs..."):
                summary = ingest_all(clear_first=True)
            if "error" in summary:
                st.error(summary["error"])
            else:
                st.success(f"{summary['docs_ingested']} docs — {summary['total_chunks']} chunks indexed")
                st.rerun()

# =============================================================================
# RIGHT COLUMN
# =============================================================================

with col2:
    st.markdown("### Research Query")

    if stats["ready"]:
        if selected_doc != "All Documents":
            st.markdown(scope_tag(selected_doc), unsafe_allow_html=True)
        elif selected_class != "All Documents":
            st.markdown(scope_tag(selected_class), unsafe_allow_html=True)
        else:
            st.markdown(scope_tag("All Documents"), unsafe_allow_html=True)
        st.markdown("")

    question = st.text_area(
        "Research question",
        placeholder=(
            "e.g. Summarize key investment risks across all documents\n"
            "e.g. What does Vanguard say about Federal Reserve policy in 2026?\n"
            "e.g. Compare the fee structures and strategies of these funds"
        ),
        height=110,
        label_visibility="collapsed",
    )

    qcol1, qcol2 = st.columns([2, 1])
    with qcol1:
        mode = st.selectbox(
            "Output mode",
            ["Q&A with citations", "IC Memo draft", "Risk summary", "Manager comparison"],
        )
    with qcol2:
        st.markdown("<br>", unsafe_allow_html=True)
        run = st.button("Run Query →", type="primary", disabled=not question, use_container_width=True)

    st.divider()
    st.markdown("### Response")

    if run and question:
        active_class = None if selected_class == "All Documents" else selected_class
        active_doc   = None if selected_doc   == "All Documents" else selected_doc

        with st.spinner("Retrieving sources and generating response..."):
            result = rag_query(
                question=question,
                mode=mode,
                asset_class=active_class,
                source=active_doc,
            )

        if result["error"]:
            st.error(result["error"])
        else:
            st.markdown(
                f'<div class="response-box">{result["response"]}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("")
            with st.expander(f"Sources retrieved ({len(result['sources'])} chunks)"):
                for i, chunk in enumerate(result["sources"]):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"**{chunk['source']}** — Page {chunk['page']}")
                        st.caption(chunk["text"][:280] + "...")
                    with c2:
                        st.markdown(badge(chunk.get("asset_class", "Other")), unsafe_allow_html=True)
                        st.caption(f"dist: {chunk['distance']}")
                    st.divider()
    else:
        st.caption("Source-grounded answers will appear here after you run a query.")
