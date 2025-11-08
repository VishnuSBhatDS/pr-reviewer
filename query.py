from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from vectorstore import get_vectorstore
from collections import defaultdict


def query_codebase_context(question: str) -> str:
    """Retrieve relevant code chunks for a question, expand to full methods, merge related tests, and save to result.txt."""
    vectordb = get_vectorstore()

    # 1️⃣ Search code chunks first
    code_docs = vectordb.similarity_search(question, k=30, filter={"type": "code"})

    # 2️⃣ Always search for tests separately (independent of code_docs count)
    test_docs = vectordb.similarity_search(question, k=5, filter={"type": "test"})

    # --- Collect picked methods (code) and picked tests separately ---
    picked_methods = {
        (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method"))
        for doc in code_docs
        if doc.metadata.get("file") and doc.metadata.get("method")
    }

    picked_tests = {
        (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method"))
        for doc in test_docs
        if doc.metadata.get("file") and doc.metadata.get("method")
    }

    # 3️⃣ Retrieve *all* stored chunks from vectorstore
    raw = vectordb.get(include=["documents", "metadatas"])
    all_docs = [
        Document(page_content=content, metadata=metadata)
        for content, metadata in zip(raw["documents"], raw["metadatas"])
    ]

    # 4️⃣ Expand all picked methods (full method reconstruction)
    full_method_docs = [
        doc
        for doc in all_docs
        if (
            doc.metadata.get("file"),
            doc.metadata.get("class"),
            doc.metadata.get("method"),
        )
        in picked_methods
    ]

    # 5️⃣ Expand all picked test cases (keep them separate for later merging)
    full_test_docs = [
        doc
        for doc in all_docs
        if (
            doc.metadata.get("file"),
            doc.metadata.get("class"),
            doc.metadata.get("method"),
        )
        in picked_tests
    ]

    # 6️⃣ Group by file and sort by chunk index
    grouped_docs = defaultdict(list)
    for doc in full_method_docs + full_test_docs:
        grouped_docs[doc.metadata.get("file", "UnknownFile")].append(doc)

    for docs in grouped_docs.values():
        docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))

    # 7️⃣ Build final readable context
    context_parts = []
    for file, docs in grouped_docs.items():
        for doc in docs:
            section_type = "TEST" if doc.metadata.get("type") == "test" else "CODE"
            context_parts.append(
                f"--- {file} | {doc.metadata.get('class', 'NoClass')} | "
                f"{doc.metadata.get('method', 'NoMethod')} | "
                f"{section_type} | {doc.metadata.get('label', 'NoLabel')} ---\n"
                f"{doc.page_content}"
            )

    context = "\n\n".join(context_parts)

    # 8️⃣ Print and save
    print(f"\nContext for question:\n{question}\n")
    print(context)

    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"Context for question:\n{question}\n\n")
        f.write(context)

    print("\n✅ Output written to result.txt (with code + related tests)")

    return context


# === Example usage ===
# question = "how do we sync minimart orders ?"
question = "/v1/minimart-order-sync"
query_codebase_context(question)
