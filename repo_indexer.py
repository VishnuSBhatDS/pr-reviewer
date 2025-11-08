import os
import tempfile
from git import Repo
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
import javalang

from config import CHROMA_PATH, embeddings

# === Method-level chunking function using javalang ===
def split_java_file(file_path, max_lines_per_chunk=50, overlap_lines=5):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()

    documents = []
    try:
        tree = javalang.parse.parse(code)
    except javalang.parser.JavaSyntaxError:
        print(f"⚠️ Syntax error in {file_path}, skipping.")
        return documents

    for path, node in tree.filter(javalang.tree.ClassDeclaration):
        class_name = node.name

        for method in node.methods:
            method_name = method.name
            start = method.position.line - 1 if method.position else 0
            method_lines = code.splitlines()[start:]
            if method.body:
                end = method.body[-1].position.line if method.body[-1].position else start + len(method_lines)
            else:
                end = start + len(method_lines)
            method_lines = code.splitlines()[start:end]

            # Split long methods
            for i in range(0, len(method_lines), max_lines_per_chunk - overlap_lines):
                sub_chunk_lines = method_lines[i:i+max_lines_per_chunk]
                chunk_text = "\n".join(sub_chunk_lines)
                label = f"{i//(max_lines_per_chunk - overlap_lines) + 1}/{max(1, len(method_lines)//(max_lines_per_chunk - overlap_lines) + 1)}"
                
                # Add metadata for prioritization
                metadata = {
                    "file": os.path.basename(file_path),
                    "class": class_name,
                    "method": method_name,
                    "label": label,
                    "type": "test" if "/test/" in file_path.lower() else "code"
                }
                documents.append(Document(page_content=chunk_text, metadata=metadata))
    return documents

# === Repo indexing function ===
def index_repo(repo_url: str, branch: str = "main") -> int:
    temp_dir = tempfile.mkdtemp()
    Repo.clone_from(repo_url, temp_dir, branch=branch)
    docs = []

    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file.endswith(".java"):
                path = os.path.join(root, file)
                try:
                    file_docs = split_java_file(path)
                    docs.extend(file_docs)
                except Exception as e:
                    print(f"⚠️ Skipped {path}: {e}")

    # Persist to Chroma
    vectordb = Chroma.from_documents(docs, embeddings, persist_directory=CHROMA_PATH)
    vectordb.persist()
    return len(docs)


# === Example usage ===
if __name__ == "__main__":
    repo_url = "https://github.com/VishnuSBhatDS/cart-service.git"
    branch = "master"
    indexed_docs = index_repo(repo_url, branch)
    print(f"Total chunks created: {indexed_docs}")
