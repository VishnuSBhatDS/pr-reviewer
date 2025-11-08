import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from vectorstore import get_vectorstore_paths


def load_vectorstore(db_path):
    """Safely load a Chroma vectorstore from a given path."""
    try:
        return Chroma(persist_directory=db_path)
    except Exception as e:
        print(f"⚠️ Failed to load {db_path}: {e}")
        return None


def search_vectorstore(vectordb, question, k_code=50, k_test=10):
    """Run code + test similarity search in a single vectorstore."""
    results = {"code": [], "test": []}
    try:
        results["code"] = vectordb.similarity_search(question, k=k_code, filter={"type": "code"})
        results["test"] = vectordb.similarity_search(question, k=k_test, filter={"type": "test"})
    except Exception as e:
        print(f"⚠️ Search failed for {vectordb._persist_directory}: {e}")
    return results


def query_codebase_context(question: str, base_chroma_path: str = "./chroma_dbs", top_k_final: int = 40) -> str:
    """
    🔍 Global search across multiple repos (each a Chroma DB).
    Combines top results, expands to full methods, and writes to result.txt.
    """
    db_paths = get_vectorstore_paths(base_chroma_path)
    if not db_paths:
        raise ValueError(f"No Chroma DBs found in {base_chroma_path}")

    # === 1️⃣ Load all vectorstores in parallel ===
    print(f"🧠 Loading {len(db_paths)} vectorstores...")
    vectorstores = []
    with ThreadPoolExecutor(max_workers=min(8, len(db_paths))) as executor:
        futures = {executor.submit(load_vectorstore, path): path for path in db_paths}
        for fut in as_completed(futures):
            vs = fut.result()
            if vs:
                vectorstores.append(vs)
    print(f"✅ Loaded {len(vectorstores)} vectorstores successfully.\n")

    # === 2️⃣ Run parallel similarity searches ===
    print(f"🔎 Searching for: {question}")
    results = {"code": [], "test": []}
    with ThreadPoolExecutor(max_workers=len(vectorstores)) as executor:
        futures = {executor.submit(search_vectorstore, vs, question): vs for vs in vectorstores}
        for fut in as_completed(futures):
            res = fut.result()
            results["code"].extend(res["code"])
            results["test"].extend(res["test"])

    print(f"✅ Retrieved {len(results['code'])} code chunks and {len(results['test'])} test chunks total.\n")

    # === 3️⃣ Deduplicate and limit ===
    def unique_docs(docs):
        seen = set()
        unique = []
        for d in docs:
            key = (d.metadata.get("file"), d.metadata.get("class"), d.metadata.get("method"))
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique

    code_docs = unique_docs(results["code"])[:top_k_final]
    test_docs = unique_docs(results["test"])[:10]

    # === 4️⃣ Expand picked methods/tests across all DBs ===
    all_docs = []
    for vs in vectorstores:
        raw = vs.get(include=["documents", "metadatas"])
        for content, metadata in zip(raw["documents"], raw["metadatas"]):
            all_docs.append(Document(page_content=content, metadata=metadata))

    picked_methods = {
        (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method"))
        for doc in code_docs
    }
    picked_tests = {
        (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method"))
        for doc in test_docs
    }

    expanded_docs = [
        doc for doc in all_docs
        if (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method")) in picked_methods
        or (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method")) in picked_tests
    ]

    # === 5️⃣ Group by repo → file → method ===
    grouped = defaultdict(list)
    for doc in expanded_docs:
        repo = doc.metadata.get("repo", "UnknownRepo")
        file = doc.metadata.get("file", "UnknownFile")
        grouped[(repo, file)].append(doc)

    for docs in grouped.values():
        docs.sort(key=lambda d: d.metadata.get("label", "0"))

    # === 6️⃣ Build final readable context ===
    context_parts = []
    for (repo, file), docs in grouped.items():
        context_parts.append(f"\n=== 🧩 {repo} → {file} ===\n")
        for doc in docs:
            section_type = "TEST" if doc.metadata.get("type") == "test" else "CODE"
            context_parts.append(
                f"--- {doc.metadata.get('class', 'NoClass')} | "
                f"{doc.metadata.get('method', 'NoMethod')} | "
                f"{section_type} | {doc.metadata.get('label', 'NoLabel')} ---\n"
                f"{doc.page_content}\n"
            )

    context = "\n".join(context_parts)

    # === 7️⃣ Save to file ===
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"Question: {question}\n\n{context}")

    return context


# Example usage
if __name__ == "__main__":
    question = "how do we sync minimart orders ? /v1/minimart-order-sync"
    query_codebase_context(question)
