import os
import tempfile
from git import Repo
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
import javalang
from config import embeddings


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
            start = method.position.line - 1 if method.position else 0

            # include annotations above method
            annotation_start = start
            while annotation_start > 0 and lines[annotation_start - 1].strip().startswith("@"):
                annotation_start -= 1

            if method.body and len(method.body) > 0:
                last_stmt = method.body[-1]
                end = getattr(last_stmt.position, "line", None)
                if not end:
                    end = start + len(lines)
            else:
                end = start + len(lines)

            end = min(end, len(lines))
            method_lines = lines[annotation_start:end]

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


def index_repo(repo_url: str, branch: str, db_name: str, base_chroma_path: str) -> int:
    """
    Clone a specific branch of a repo and index into a Chroma DB named after db_name.
    Each branch will get its own separate vector DB folder.
    """
    temp_dir = tempfile.mkdtemp()
    repo = Repo.clone_from(repo_url, temp_dir)
    repo.git.checkout(branch)

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

    db_path = os.path.join(base_chroma_path, db_name)
    os.makedirs(db_path, exist_ok=True)

    vectordb = Chroma.from_documents(docs, embeddings, persist_directory=db_path)
    vectordb.persist()
    print(f"✅ Indexed {len(docs)} documents into {db_path}")
    return len(docs)


def index_multiple_repos(repo_configs, base_chroma_path="./chroma_dbs"):
    """
    Index multiple repos and branches into separate Chroma DBs.
    repo_configs = [
        {
            "repo_url": "https://github.com/VishnuSBhatDS/cart-service.git",
            "branch": "master",
            "db_name": "cart_master"
        },
        {
            "repo_url": "https://github.com/VishnuSBhatDS/inventory-service.git",
            "branch": "develop",
            "db_name": "inventory_dev"
        }
    ]
    """
    total_docs = 0
    for config in repo_configs:
        total_docs += index_repo(
            repo_url=config["repo_url"],
            branch=config["branch"],
            db_name=config["db_name"],
            base_chroma_path=base_chroma_path
        )
    print(f"🔥 Total indexed across all repos: {total_docs}")
    return total_docs


if __name__ == "__main__":
    repo_configs = [
        {
            "repo_url": "https://github.com/VishnuSBhatDS/cart-service.git",
            "branch": "master",
            "db_name": "cart-service"
        },
        {
            "repo_url": "https://github.com/VishnuSBhatDS/chat-service.git",
            "branch": "main",
            "db_name": "chat-service"
        }
    ]
    index_repo(
        repo_url="https://github.com/VishnuSBhatDS/payment-service.git",
        branch="master",
        db_name="payment-service",
        base_chroma_path="./chroma_dbs"
    )