from langchain_community.vectorstores import Chroma
from config import CHROMA_PATH, embeddings

def get_vectorstore() -> Chroma:
    """Load persisted Chroma vectorstore."""
    return Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
