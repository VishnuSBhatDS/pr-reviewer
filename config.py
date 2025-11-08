import os
from langchain_huggingface import HuggingFaceEmbeddings

CHROMA_PATH = "../chroma_repo_codellama"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "codellama"
HF_TOKEN = os.getenv("HUGGINGFACEHUB_API_TOKEN")

# Embeddings setup
embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
