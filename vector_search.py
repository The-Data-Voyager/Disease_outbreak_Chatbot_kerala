"""IDSP Kerala — Vector Search Module"""

import os
import chromadb
from google import genai
from dotenv import load_dotenv
from typing import Optional


EMBEDDING_MODEL = "gemini-embedding-001"


class VectorSearch:
    def __init__(self, chroma_path: str, env_path: str = ".env"):
        load_dotenv(env_path)
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env")
        self.gemini_client = genai.Client(api_key=api_key)

        chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = chroma_client.get_collection("idsp_kerala")

    def search(self, question: str, n_results: int = 5,
               where: Optional[dict] = None) -> dict:
        q_result = self.gemini_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=question,
            config={"task_type": "RETRIEVAL_QUERY"}
        )
        q_embedding = q_result.embeddings[0].values

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
