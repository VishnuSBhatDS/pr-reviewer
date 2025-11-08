import os
import tempfile
from git import Repo
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
import javalang
from config import CHROMA_PATH, embeddings


def split_java_file(file_path, max_lines_per_chunk=50, overlap_lines=5):
    """Split a Java file into annotated method-level chunks."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()

    lines = code.splitlines()
    documents = []

    try:
        tree = javalang.parse.parse(code)
    except javalang.parser.JavaSyntaxError:
        print(f"⚠️ Syntax error in {file_path}, skipping.")
        return documents

    for _, node in tree.filter(javalang.tree.ClassDeclaration):
        class_name = node.name

        for method in node.methods:
            method_name = method.name

            # === 1️⃣ Determine start line ===
            start = method.position.line - 1 if method.position else 0

            # Go upward to include all contiguous @annotation lines
            annotation_start = start
            while annotation_start > 0 and lines[annotation_start - 1].strip().startswith("@"):
                annotation_start -= 1

            # === 2️⃣ Determine end line ===
            if method.body and len(method.body) > 0:
                last_stmt = method.body[-1]
                end = getattr(last_stmt.position, "line", None)
                if not end:
                    end = start + len(lines)  # fallback
            else:
                end = start + len(lines)
            
            # Cap at total lines
            end = min(end, len(lines))

            # === 3️⃣ Extract the annotated block ===
            method_lines = lines[annotation_start:end]

            # === 4️⃣ Split long methods ===
            for i in range(0, len(method_lines), max_lines_per_chunk - overlap_lines):
                sub_chunk_lines = method_lines[i:i + max_lines_per_chunk]
                chunk_text = "\n".join(sub_chunk_lines)
                label = f"{i // (max_lines_per_chunk - overlap_lines) + 1}/{max(1, len(method_lines) // (max_lines_per_chunk - overlap_lines) + 1)}"

                metadata = {
                    "file": os.path.basename(file_path),
                    "class": class_name,
                    "method": method_name,
                    "label": label,
                    "type": "test" if "/test/" in file_path.lower() else "code"
                }

                documents.append(Document(page_content=chunk_text, metadata=metadata))

    return documents


def index_repo(repo_url: str, branch: str = "main") -> int:
    """Clone and index a Java repo into Chroma vector DB."""
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

    vectordb = Chroma.from_documents(docs, embeddings, persist_directory=CHROMA_PATH)
    vectordb.persist()
    return len(docs)


if __name__ == "__main__":
    repo_url = "https://github.com/VishnuSBhatDS/cart-service.git"
    branch = "master"
    indexed_docs = index_repo(repo_url, branch)
    print(f"Total chunks created: {indexed_docs}")
