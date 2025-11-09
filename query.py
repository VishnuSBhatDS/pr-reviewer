import os
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from vectorstore import get_vectorstore_paths
from info_query import query_service_info
from config import embeddings


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


def rerank_globally(search_results, question, embeddings, top_k_final=50):
    """Combine all retrieved docs and rerank them globally using semantic similarity."""
    all_docs = []
    for res in search_results:
        all_docs.extend(res["code"] + res["test"])

    if not all_docs:
        print("⚠️ No documents retrieved for reranking.")
        return []

    print(f"🧠 Reranking {len(all_docs)} documents globally...")

    # Compute query embedding
    query_emb = np.array(embeddings.embed_query(question))

    # Compute document embeddings (truncate to avoid massive text)
    doc_embeddings = np.array([embeddings.embed_query(d.page_content[:1000]) for d in all_docs])

    # Compute cosine similarities
    sims = np.dot(doc_embeddings, query_emb) / (
        np.linalg.norm(doc_embeddings, axis=1) * np.linalg.norm(query_emb)
    )

    # Attach scores
    doc_scores = list(zip(all_docs, sims))
    ranked_docs = sorted(doc_scores, key=lambda x: x[1], reverse=True)
    top_docs = [doc for doc, _ in ranked_docs[:top_k_final]]

    print(f"✅ Reranked and selected top {len(top_docs)} most relevant docs globally.\n")
    return top_docs


def query_codebase_context(question: str, base_chroma_path: str = "./chroma_dbs", top_k_final: int = 40) -> str:
    """
    🔍 Multi-repo intelligent query with global reranking.
    Groups results by service → file → method.
    """
    db_paths = get_vectorstore_paths(base_chroma_path)
    if not db_paths:
        raise ValueError(f"No Chroma DBs found in {base_chroma_path}")

    # === 1️⃣ Load vectorstores ===
    print(f"🧠 Loading {len(db_paths)} vectorstores...")
    vectorstores = []
    failed_services = {}

    with ThreadPoolExecutor(max_workers=min(8, len(db_paths))) as executor:
        futures = {executor.submit(load_vectorstore, path): path for path in db_paths}
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                vs = fut.result()
                if vs:
                    vectorstores.append(vs)
                else:
                    failed_services[path] = "Returned None (load failed silently)"
            except Exception as e:
                failed_services[path] = str(e)

    print(f"✅ Loaded {len(vectorstores)} services successfully.\n")
    if failed_services:
        print("⚠️ Some vectorstores failed to load:\n")
        for path, err in failed_services.items():
            print(f"  ❌ {path} → {err}")

    # === 2️⃣ Search in all vectorstores ===
    print(f"🔎 Searching for: {question}\n")
    search_results = []
    with ThreadPoolExecutor(max_workers=len(vectorstores)) as executor:
        futures = {executor.submit(search_vectorstore, vs, question): vs for vs in vectorstores}
        for fut in as_completed(futures):
            res = fut.result()
            total_hits = len(res["code"]) + len(res["test"])
            print(f"  ✅ {res['service']}: {len(res['code'])} code, {len(res['test'])} test → total {total_hits}")
            search_results.append(res)

    print("\n📊 Summary of search results:")
    for res in search_results:
        print(f"  • {res['service']}: {len(res['code'])} code | {len(res['test'])} test")
    print()

    # === 3️⃣ Global semantic reranking ===
    top_docs = rerank_globally(search_results, question, embeddings, top_k_final=top_k_final)

    # === 4️⃣ Group by service ===
    grouped_by_service = defaultdict(lambda: defaultdict(list))
    for doc in top_docs:
        service = (
            doc.metadata.get("serviceName")
            or doc.metadata.get("service")
            or getattr(doc, "service_name", "UnknownService")
        )
        file = doc.metadata.get("file", "UnknownFile")
        grouped_by_service[service][file].append(doc)

    # Sort chunks by label
    for service_docs in grouped_by_service.values():
        for docs in service_docs.values():
            docs.sort(key=lambda d: d.metadata.get("label", "0"))

    # === 5️⃣ Build output ===
    context_parts = []
    for service, files in grouped_by_service.items():
        context_parts.append(f"\n🟦 SERVICE: {service}\n" + "=" * 70)
        for file, docs in files.items():
            seen = set()
            context_parts.append(f"\n📄 FILE: {file}\n")
            for doc in docs:
                key = (doc.metadata.get("class"), doc.metadata.get("method"), doc.metadata.get("label"))
                if key in seen:
                    continue
                seen.add(key)
                section_type = "TEST" if doc.metadata.get("type") == "test" else "CODE"
                context_parts.append(
                    f"--- {doc.metadata.get('class', 'NoClass')} | "
                    f"{doc.metadata.get('method', 'NoMethod')} | "
                    f"{section_type} | {doc.metadata.get('label', 'NoLabel')} ---\n"
                    f"{doc.page_content}\n"
                )

    context = "\n".join(context_parts)

    # === 6️⃣ Save output ===
    with open("result.txt", "w", encoding="utf-8") as f:
        f.write(f"Question: {question}\n\n{context}")

    print(f"\n✅ Final results written to result.txt ({len(top_docs)} relevant chunks)\n")
    return context


# === Example usage ===
if __name__ == "__main__":
    question = "how do we sync minimart orders ?"
    query_codebase_context(question)
