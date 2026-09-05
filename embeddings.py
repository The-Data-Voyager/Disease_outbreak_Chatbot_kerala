"""Local sentence-embedding model for IDSP Kerala (BAAI/bge-small-en-v1.5).

Runs fully offline via sentence-transformers: no API key, no quota, no rate
limits. Used for both document embedding (ingest) and query embedding (search)
so stored vectors and query vectors share one space.
"""

from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"

# bge retrieval works best when the *query* carries this instruction.
# Passages/documents are embedded without any prefix.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def embed_documents(texts):
    """Embed passages/documents. Returns a list of float lists (unit-normalized)."""
    model = _get_model()
    vectors = model.encode(
        list(texts), normalize_embeddings=True, show_progress_bar=False
    )
    return [v.tolist() for v in vectors]


def embed_query(text):
    """Embed a single search query (with the bge query instruction)."""
    model = _get_model()
    vector = model.encode(
        QUERY_INSTRUCTION + text, normalize_embeddings=True, show_progress_bar=False
    )
    return vector.tolist()
