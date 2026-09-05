"""IDSP Kerala - Vector Search Module (local bge-small-en-v1.5 embeddings)"""

import chromadb
from typing import Optional

from embeddings import embed_query


class VectorSearch:
    def __init__(self, chroma_path: str):
        chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = chroma_client.get_collection("idsp_kerala")

    def search(self, question: str, n_results: int = 5,
               where: Optional[dict] = None) -> dict:
        q_embedding = embed_query(question)

        kwargs = {
            "query_embeddings": [q_embedding],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        return self.collection.query(**kwargs)

    def get_context(self, question: str, n_results: int = 5,
                    where: Optional[dict] = None) -> str:
        results = self.search(question, n_results, where)
        if not results["documents"][0]:
            return "No relevant documents found."
        context_parts = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            context_parts.append(f"[{meta['doc_type']}] {doc}")
        return "\n\n---\n\n".join(context_parts)
