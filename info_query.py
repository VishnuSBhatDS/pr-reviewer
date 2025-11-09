import os
import re
from collections import Counter
from langchain_community.vectorstores import Chroma
from config import embeddings


def preprocess_text(text: str) -> set[str]:
    """Normalize text for keyword matching."""
    return set(re.findall(r"\b\w+\b", text.lower()))


def compute_keyword_score(query_tokens: set[str], doc_keywords: dict) -> int:
    """Compute how many keywords overlap between query and metadata."""
    if not doc_keywords:
        return 0
    all_keywords = []
    for group in doc_keywords.values():
        all_keywords.extend(group)
    all_tokens = preprocess_text(" ".join(all_keywords))
    return len(query_tokens.intersection(all_tokens))


def query_service_info(
    question: str,
    chroma_db_path: str = "./chroma_dbs/service_info",
    top_k: int = 10,
    keyword_weight: float = 2.0,
    semantic_weight: float = 1.0,
    output_file: str = "service_info.txt",
):
    """
    Hybrid search combining embedding similarity and keyword-based boosting.
    """
    if not os.path.exists(chroma_db_path):
        raise FileNotFoundError(f"Chroma DB path does not exist: {chroma_db_path}")

    vectordb = Chroma(persist_directory=chroma_db_path, embedding_function=embeddings)
    query_tokens = preprocess_text(question)

    # --- Step 1: Semantic search ---
    results_with_scores = vectordb.similarity_search_with_score(question, k=top_k)

    # --- Step 2: Collect keyword-matching docs (in case minimart was missed) ---
    all_docs = vectordb.get()["metadatas"]
    keyword_hits = []
    for i, meta in enumerate(all_docs):
        doc_keywords = meta.get("keywords")
        if doc_keywords:
            all_kw = preprocess_text(" ".join(sum(doc_keywords.values(), [])))
            if query_tokens & all_kw:
                # Wrap into pseudo-doc-like structure if not in top_k
                keyword_hits.append((i, len(query_tokens & all_kw)))

    # --- Step 3: Merge and re-rank ---
    doc_scores = {}

    # From embedding search
    for doc, sim_score in results_with_scores:
        keyword_score = compute_keyword_score(query_tokens, doc.metadata.get("keywords"))
        final_score = semantic_weight * sim_score + keyword_weight * keyword_score
        doc_scores[id(doc)] = (doc, final_score)

    # Add any missing docs that matched keywords but weren’t retrieved semantically
    for i, kw_score in keyword_hits:
        # Retrieve document manually by index from vectorstore
        meta = vectordb.get()["metadatas"][i]
        content = vectordb.get()["documents"][i]
        fake_doc = type("Doc", (), {"page_content": content, "metadata": meta})
        final_score = keyword_weight * kw_score
        doc_scores[id(fake_doc)] = (fake_doc, final_score)

    # --- Step 4: Sort by final combined score ---
    ranked_docs = sorted(doc_scores.values(), key=lambda x: x[1], reverse=True)

    # --- Step 5: Group by service ---
    service_docs = {}
    for doc, _ in ranked_docs:
        service = doc.metadata.get("serviceName", "UnknownService")
        service_docs.setdefault(service, []).append(doc)

    # --- Step 6: Pick top 2 services ---
    top_services_counter = Counter({k: len(v) for k, v in service_docs.items()})
    top_services = [s for s, _ in top_services_counter.most_common(3)]

    print(f"🏆 Top services for your query: {', '.join(top_services)}\n")

    # --- Step 7: Write output file ---
    output_lines = [f"Question: {question}\n", "=" * 80 + "\n"]
    for service in top_services:
        docs = service_docs[service]
        output_lines.append(f"🟦 SERVICE: {service}\n")
        output_lines.append("-" * 60 + "\n")
        for doc in docs:
            section = doc.metadata.get("section", "parent")
            output_lines.append(f"📄 Section: {section}\n{doc.page_content}\n\n")

    output_text = "\n".join(output_lines)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"✅ Query results saved to {output_file}")
    return top_services


if __name__ == "__main__":
    user_question = input("Enter your query: ")
    print(query_service_info(user_question))
