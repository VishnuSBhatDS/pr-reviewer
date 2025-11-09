import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from vectorstore import get_vectorstore_paths
from info_query import query_service_info


def load_vectorstore(db_path):
    """Load a Chroma DB and tag it with the service name."""
    try:
        service_name = os.path.basename(db_path)
        vectordb = Chroma(persist_directory=db_path)
        vectordb.service_name = service_name  # tag for reference
        return vectordb
    except Exception as e:
        print(f"⚠️ Failed to load {db_path}: {e}")
        return None


def search_vectorstore(vectordb, question, k_code=50, k_test=10):
    """Perform similarity searches (code + test) on a single vectorstore."""
    results = {"service": vectordb.service_name, "code": [], "test": []}
    try:
        results["code"] = vectordb.similarity_search(question, k=k_code, filter={"type": "code"})
        results["test"] = vectordb.similarity_search(question, k=k_test, filter={"type": "test"})
    except Exception as e:
        print(f"⚠️ Search failed in {vectordb.service_name}: {e}")
    return results


def query_codebase_context(question: str, base_chroma_path: str = "./chroma_dbs", top_k_final: int = 40) -> str:
    """
    🔍 Multi-repo intelligent query.
    Groups results by service → file → method.
    """
    # db_paths = get_vectorstore_paths(base_chroma_path)
    top_services = query_service_info(question)
    db_paths = [os.path.join(base_chroma_path, d) for d in top_services]
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
    print(f"✅ Loaded {len(vectorstores)} services successfully.\n")

    # === 2️⃣ Run searches in parallel ===
    print(f"🔎 Searching for: {question}")
    search_results = []
    with ThreadPoolExecutor(max_workers=len(vectorstores)) as executor:
        futures = {executor.submit(search_vectorstore, vs, question): vs for vs in vectorstores}
        for fut in as_completed(futures):
            search_results.append(fut.result())

    # === 3️⃣ Collect results per service ===
    all_service_docs = defaultdict(lambda: {"code": [], "test": []})
    for res in search_results:
        service = res["service"]
        all_service_docs[service]["code"].extend(res["code"])
        all_service_docs[service]["test"].extend(res["test"])

    # === 4️⃣ Deduplicate and limit top results per service ===
    def unique_docs(docs):
        seen = set()
        unique = []
        for d in docs:
            key = (d.metadata.get("file"), d.metadata.get("class"), d.metadata.get("method"))
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique

    for service in all_service_docs:
        all_service_docs[service]["code"] = unique_docs(all_service_docs[service]["code"])[:top_k_final]
        all_service_docs[service]["test"] = unique_docs(all_service_docs[service]["test"])[:10]

    # === 5️⃣ Expand relevant methods + tests ===
    expanded_docs = defaultdict(list)
    for vs in vectorstores:
        raw = vs.get(include=["documents", "metadatas"])
        all_docs = [Document(page_content=c, metadata=m) for c, m in zip(raw["documents"], raw["metadatas"])]

        service = vs.service_name
        picked = {
            (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method"))
            for doc in (all_service_docs[service]["code"] + all_service_docs[service]["test"])
        }

        for doc in all_docs:
            key = (doc.metadata.get("file"), doc.metadata.get("class"), doc.metadata.get("method"))
            if key in picked:
                expanded_docs[service].append(doc)

    # === 6️⃣ Group within each service by file ===
    grouped_by_service = defaultdict(lambda: defaultdict(list))
    for service, docs in expanded_docs.items():
        for doc in docs:
            file = doc.metadata.get("file", "UnknownFile")
            grouped_by_service[service][file].append(doc)

    # Sort chunks by label for better readability
    for service_docs in grouped_by_service.values():
        for docs in service_docs.values():
            docs.sort(key=lambda d: d.metadata.get("label", "0"))

    # === 7️⃣ Build final output ===
    context_parts = []
    for service, files in grouped_by_service.items():
        context_parts.append(f"\n🟦 SERVICE: {service}\n" + "=" * 70)
        for file, docs in files.items():
            seen = set()
            context_parts.append(f"\n📄 FILE: {file}\n")
            for doc in docs:
                key = (doc.metadata.get("class"), doc.metadata.get("method"), doc.metadata.get("label"))
                if key in seen:
                    continue  # skip duplicate
                seen.add(key)

                section_type = "TEST" if doc.metadata.get("type") == "test" else "CODE"
                context_parts.append(
                    f"--- {doc.metadata.get('class', 'NoClass')} | "
                    f"{doc.metadata.get('method', 'NoMethod')} | "
                    f"{section_type} | {doc.metadata.get('label', 'NoLabel')} ---\n"
                    f"{doc.page_content}\n"
                )


    context = "\n".join(context_parts)

    # === 8️⃣ Save output ===
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"Question: {question}\n\n{context}")

    return context


# === Example usage ===
if __name__ == "__main__":
    question = "how do we sync minimart orders ?"
    query_codebase_context(question)
