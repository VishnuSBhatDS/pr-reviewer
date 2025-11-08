from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from vectorstore import get_vectorstore
from collections import defaultdict


def query_codebase_context(question: str) -> str:
    """Retrieve relevant code chunks for a question, expand to full methods, and save to result.txt."""
    vectordb = get_vectorstore()

    # 1️⃣ Search in 'code' documents first
    code_docs = vectordb.similarity_search(
        question, k=20, filter={"type": "code"}
    )

    # Collect method identifiers from results
    picked_methods = {
        (
            doc.metadata.get("file"),
            doc.metadata.get("class"),
            doc.metadata.get("method"),
        )
        for doc in code_docs
        if doc.metadata.get("file") and doc.metadata.get("method")
    }

    # 2️⃣ If fewer than 20, fill with 'test' documents
    if len(code_docs) < 20:
        remaining = 20 - len(code_docs)
        test_docs = vectordb.similarity_search(
            question, k=remaining, filter={"type": "test"}
        )
        picked_methods.update(
            {
                (
                    doc.metadata.get("file"),
                    doc.metadata.get("class"),
                    doc.metadata.get("method"),
                )
                for doc in test_docs
                if doc.metadata.get("file") and doc.metadata.get("method")
            }
        )
        final_docs = code_docs + test_docs
    else:
        final_docs = code_docs

    # 3️⃣ Retrieve all stored chunks
    raw = vectordb.get(include=["documents", "metadatas"])
    all_docs = [
        Document(page_content=content, metadata=metadata)
        for content, metadata in zip(raw["documents"], raw["metadatas"])
    ]

    # 4️⃣ Filter all chunks that belong to any picked (file, class, method)
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

    # 5️⃣ Group by file and sort chunks by index
    grouped_docs = defaultdict(list)
    for doc in full_method_docs:
        grouped_docs[doc.metadata.get("file", "UnknownFile")].append(doc)

    for docs in grouped_docs.values():
        docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))

    # 6️⃣ Build final readable context
    context_parts = []
    for file, docs in grouped_docs.items():
        for doc in docs:
            context_parts.append(
                f"--- {file} | {doc.metadata.get('class', 'NoClass')} | "
                f"{doc.metadata.get('method', 'NoMethod')} | "
                f"{doc.metadata.get('label', 'NoLabel')} ---\n{doc.page_content}"
            )

    context = "\n\n".join(context_parts)

    # 7️⃣ Print and save
    print(f"\nContext for question:\n{question}\n")
    print(context)

    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"Context for question:\n{question}\n\n")
        f.write(context)

    print("\n✅ Output written to result.txt")

    return context


# === Example usage ===
question = "will decimal delivery fee fail for this api order/cancellation/panel??"
query_codebase_context(question)
