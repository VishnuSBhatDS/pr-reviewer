import os
import json
import hashlib
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from config import embeddings


def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_parent_doc(json_data, file_name):
    """
    Creates a single parent doc with only top-level scalar keys.
    """
    service_name = json_data.get("serviceName", file_name.split(".")[0])
    parent_content = {
        k: v for k, v in json_data.items() if not isinstance(v, (dict, list))
    }

    if not parent_content:
        return None

    return Document(
        page_content=json.dumps(parent_content, indent=2),
        metadata={
            "serviceName": service_name,
            "file": file_name,
            "section": "parent",
            "childLevel": 0
        }
    )


def create_child_docs(json_data, file_name):
    """
    Creates child docs for all top-level keys that are dicts or lists.
    """
    service_name = json_data.get("serviceName", file_name.split(".")[0])
    child_docs = []

    for key, value in json_data.items():
        if isinstance(value, (dict, list)):
            doc_content = json.dumps({key: value}, indent=2)
            doc_id = hashlib.md5(doc_content.encode()).hexdigest()
            doc = Document(
                page_content=doc_content,
                metadata={
                    "serviceName": service_name,
                    "file": file_name,
                    "section": key,
                    "childLevel": 1,
                    "docId": doc_id
                }
            )
            child_docs.append(doc)

    return child_docs


def embed_single_info_file(file_path, chroma_db_path="./chroma_dbs/service_info"):
    """
    Embeds a single JSON info file into the service_info DB.
    Replaces previous docs from the same file.
    """
    os.makedirs(chroma_db_path, exist_ok=True)
    file_name = os.path.basename(file_path)
    json_data = load_json(file_path)

    # Parent + child docs
    documents = []
    parent_doc = create_parent_doc(json_data, file_name)
    if parent_doc:
        # Add a docId for parent as well
        parent_doc.metadata["docId"] = hashlib.md5(parent_doc.page_content.encode()).hexdigest()
        documents.append(parent_doc)

    documents.extend(create_child_docs(json_data, file_name))

    # Load existing DB
    vectordb = Chroma(persist_directory=chroma_db_path, embedding_function=embeddings)

    # Delete previous docs for this file
    all_docs = vectordb.get(include=["metadatas", "documents"])
    ids_to_delete = []
    if "ids" in all_docs:
        for doc_id, meta in zip(all_docs["ids"], all_docs["metadatas"]):
            if meta.get("file") == file_name:
                ids_to_delete.append(doc_id)
    else:
        # fallback using docId in metadata
        for meta in all_docs["metadatas"]:
            if meta.get("file") == file_name and meta.get("docId"):
                ids_to_delete.append(meta["docId"])

    if ids_to_delete:
        vectordb.delete(ids=ids_to_delete)

    # Add new docs
    vectordb.add_documents(documents)
    vectordb.persist()

    print(f"✅ Indexed {len(documents)} documents for {file_name} into {chroma_db_path}")
    return len(documents)


def embed_multiple_info_files(file_paths, chroma_db_path="./chroma_dbs/service_info"):
    """
    Embeds multiple JSON info files into service_info DB.
    """
    total_docs = 0
    for f in file_paths:
        total_docs += embed_single_info_file(f, chroma_db_path)
    print(f"🔥 Total indexed across all files: {total_docs}")
    return total_docs


if __name__ == "__main__":
    # Example single file embedding
    embed_single_info_file("../info_jsons/inventory-service.json")

    # Example multi-file embedding
    # embed_multiple_info_files([
    #     "../info_jsons/cart-service.json",
    #     "../info_jsons/payment-service.json"
    # ])
