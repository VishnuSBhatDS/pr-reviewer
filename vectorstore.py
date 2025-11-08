from langchain_community.vectorstores import Chroma
from config import CHROMA_PATH, embeddings
import os

def get_vectorstore_paths(base_chroma_path="./chroma_dbs"):
    """Return all Chroma DB directories under the base path."""
    if not os.path.exists(base_chroma_path):
        return []
    return [
        os.path.join(base_chroma_path, d)
        for d in os.listdir(base_chroma_path)
        if os.path.isdir(os.path.join(base_chroma_path, d))
    ]

def get_vectorstore() -> Chroma:
    """Load persisted Chroma vectorstore."""
    return Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
