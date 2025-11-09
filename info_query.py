import os
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from config import embeddings

def query_service_info(question: str, chroma_db_path="./chroma_dbs/service_info", top_k=10, output_file="service_info.txt"):
    """
    Query the single Chroma DB containing multiple services.
    Saves results into a text file.
    """
    if not os.path.exists(chroma_db_path):
        raise FileNotFoundError(f"Chroma DB path does not exist: {chroma_db_path}")

    # Load the DB
    vectordb = Chroma(persist_directory=chroma_db_path, embedding_function=embeddings)

    # Do similarity search (metadata is returned automatically)
    results = vectordb.similarity_search(question, k=top_k)

    # Group by service
    service_docs = {}
    for doc in results:
        service = doc.metadata.get("serviceName", "UnknownService")
        service_docs.setdefault(service, []).append(doc)

    # Build output text
    output_lines = [f"Question: {question}\n", "="*80 + "\n"]
    for service, docs in service_docs.items():
        output_lines.append(f"🟦 SERVICE: {service}\n")
        output_lines.append("-"*60 + "\n")
        for doc in docs:
            section = doc.metadata.get("section", "parent")
            output_lines.append(f"📄 Section: {section}\n{doc.page_content}\n\n")

    output_text = "\n".join(output_lines)

    # Save to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"✅ Query results saved to {output_file}")
    return output_text


if __name__ == "__main__":
    user_question = input("Enter your query: ")
    query_service_info(user_question)
