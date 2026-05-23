import streamlit as st
from ingest import ingest_all, get_collection_stats
from rag import query as rag_query

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

    stats = get_collection_stats()

    if stats["ready"]:
        st.success(f"Vector store ready — {stats['total_chunks']} chunks indexed")

        # Asset class filter
        asset_class_options = ["All Documents"] + stats["asset_classes"]
        selected_class = st.selectbox("Filter by asset class", asset_class_options)

        # Document filter — scoped to selected asset class
        doc_class_map = stats.get("doc_class_map", {})
        if selected_class == "All Documents":
            filtered_docs = stats["documents"]
        else:
            filtered_docs = [
                d for d, c in doc_class_map.items()
                if c == selected_class
            ]

        selected_doc = st.selectbox("Filter by document", ["All Documents"] + sorted(filtered_docs))

    else:
        st.info("No documents indexed yet. Click Ingest to load PDFs from data/raw_pdfs/.")
        selected_class = "All Documents"
        selected_doc = "All Documents"

    if st.button("Ingest Documents", type="primary"):
        with st.spinner("Classifying and ingesting PDFs — this may take a minute..."):
            summary = ingest_all(clear_first=True)

        if "error" in summary:
            st.error(summary["error"])
        else:
            st.success(
                f"Ingested {summary['docs_ingested']} document(s), "
                f"{summary['total_chunks']} chunks indexed"
            )
            with st.expander("Details"):
                for filename, res in summary["results"].items():
                    st.write(f"- **{filename}**: {res['chunks']} chunks — *{res['asset_class']}*")
            st.rerun()

with col2:
    st.subheader("Research Query")

    # Show active scope
    if stats["ready"]:
        if selected_doc != "All Documents":
            st.caption(f"Scope: **{selected_doc}**")
        elif selected_class != "All Documents":
            st.caption(f"Scope: **{selected_class}**")
        else:
            st.caption("Scope: **All Documents**")

    question = st.text_area(
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

    run = st.button("Run Query", type="primary", disabled=not question)

    st.divider()
    st.subheader("Response")

    if run and question:
        # Resolve filter values
        active_class = None if selected_class == "All Documents" else selected_class
        active_doc = None if selected_doc == "All Documents" else selected_doc

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
            st.markdown(result["response"])

            with st.expander(f"Sources used ({len(result['sources'])} chunks retrieved)"):
                for i, chunk in enumerate(result["sources"]):
                    st.markdown(
                        f"**Source {i+1}:** {chunk['source']} — Page {chunk['page']} "
                        f"| *{chunk.get('asset_class', 'Unknown')}* "
                        f"| similarity distance: {chunk['distance']}"
                    )
                    st.caption(chunk["text"][:300] + "...")
                    st.divider()
    else:
        st.caption("Source-grounded answers will appear here after you run a query.")
