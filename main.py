from fastapi import FastAPI
from pydantic import BaseModel
from repo_indexer import index_repo
from query import query_codebase

app = FastAPI(title="CodeLlama Repo Chatbot")

class QueryRequest(BaseModel):
    question: str

@app.get("/index")
def index_endpoint(repo_url: str, branch: str = "main"):
    """Index a repo into Chroma vectorstore."""
    indexed_docs = index_repo(repo_url, branch)
    return {"status": "success", "indexed_docs": indexed_docs}

@app.post("/query")
def query_endpoint(req: QueryRequest):
    """Query indexed repo."""
    answer = query_codebase(req.question)
    return {"answer": answer}
