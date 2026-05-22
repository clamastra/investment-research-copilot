import streamlit as st

st.set_page_config(
    page_title="CapitalContext",
    page_icon="📄",
    layout="wide",
)

st.title("CapitalContext")
st.caption("Institutional Investment Document Intelligence")

st.divider()

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Document Library")
    uploaded = st.file_uploader(
        "Upload investment documents",
        type=["pdf"],
        accept_multiple_files=True,
        help="Accepts pension reports, IPS, manager letters, SEC filings, DDQs, etc.",
    )
    if uploaded:
        st.success(f"{len(uploaded)} document(s) ready to ingest")
        if st.button("Ingest Documents", type="primary"):
            st.info("Ingestion pipeline coming in Week 2.")
    else:
        st.info("No documents loaded. Upload PDFs to begin.")

with col2:
    st.subheader("Research Query")
    query = st.text_area(
        "Enter your research question",
        placeholder=(
            "e.g. Summarize key risks across uploaded documents\n"
            "e.g. Extract fee structures and compare managers\n"
            "e.g. Identify liquidity constraints mentioned in the IPS"
        ),
        height=120,
    )

    mode = st.selectbox(
        "Output mode",
        ["Q&A with citations", "IC Memo draft", "Risk summary", "Manager comparison"],
    )

    if st.button("Run Query", type="primary", disabled=not query):
        st.info("RAG pipeline coming in Week 2.")

    st.divider()
    st.subheader("Response")
    st.caption("Source-grounded answers will appear here once the RAG pipeline is connected.")
    st.empty()
