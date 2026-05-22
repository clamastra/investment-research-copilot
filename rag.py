# Retrieval-augmented generation pipeline
# Week 2-3: semantic retrieval from ChromaDB + Claude API response generation

def retrieve(query: str, n_results: int = 5):
    raise NotImplementedError("Retrieval pipeline coming in Week 2")

def generate_response(query: str, context_chunks: list, mode: str = "qa"):
    raise NotImplementedError("Response generation coming in Week 3")
