"""Phase 5: embeddings for vector search, two models side by side.

  3small  OpenAI text-embedding-3-small (1536 dims), through the apiyi relay
  bgem3   BAAI/bge-m3 (1024 dims), self-hosted - for now on this Mac, CPU

What gets embedded for each chunk is a one-line header plus its text:
    "<file> | <page or line range or heading>\\n<chunk text>"
so a chunk can be found by what file and section it is from, not only by its
words. Both models embed exactly the same strings, so the comparison is fair.

Vectors are normalised and cached in parsed/embeddings/<model>.npz (keyed by
chunk_id and a hash of the chunk text, so a re-chunk invalidates them).
Search is exact cosine similarity over all chunks: with 25 chunks this gives
the same ranking pgvector would, so Postgres can wait for phase 6.

    .venv/bin/python scripts/embed.py   # (re)build both caches
"""
import hashlib
import pathlib
import sys
import threading

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import library as L  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "parsed" / "embeddings"
MODELS = {"3small": "text-embedding-3-small", "bgem3": "BAAI/bge-m3"}
_bge = None
_lock = threading.Lock()  # score.py runs questions in parallel threads


def chunk_input(ch):
    where = ch.get("loc") or ch.get("heading") or ""
    return f"{ch['file']} | {where}\n{ch['text']}"


def _normalise(m):
    m = np.asarray(m, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def embed_texts(model, texts):
    if model == "3small":
        from openai_client import client
        resp = client().embeddings.create(model=MODELS[model], input=texts)
        return _normalise([d.embedding for d in resp.data]), resp.usage.prompt_tokens
    if model == "bgem3":
        global _bge
        with _lock:
            if _bge is None:
                from sentence_transformers import SentenceTransformer
                _bge = SentenceTransformer(MODELS[model])
            return _normalise(_bge.encode(texts, batch_size=8)), 0
    raise ValueError(model)


def _fingerprint(chunks):
    h = hashlib.sha256()
    for ch in chunks:
        h.update(ch["chunk_id"].encode() + chunk_input(ch).encode())
    return h.hexdigest()[:16]


_index = {}


def index(model):
    """(chunk list, matrix) for a model, building the cache if it is stale."""
    if model not in _index:
        _index[model] = _build_index(model)
    return _index[model]


def _build_index(model):
    chunks = L.chunks()
    path = CACHE / f"{model}.npz"
    fp = _fingerprint(chunks)
    if path.exists():
        z = np.load(path, allow_pickle=False)
        if str(z["fingerprint"]) == fp:
            return chunks, z["vectors"]
    vectors, tokens = embed_texts(model, [chunk_input(ch) for ch in chunks])
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez(path, vectors=vectors, fingerprint=fp)
    print(f"embedded {len(chunks)} chunks with {MODELS[model]} ({tokens} tokens)", file=sys.stderr)
    return chunks, vectors


def search(model, query, k):
    """Top-k chunks for a query: list of (score, chunk), best first."""
    chunks, vectors = index(model)
    q, _ = embed_texts(model, [query])
    scores = vectors @ q[0]
    order = np.argsort(-scores)[:k]
    return [(float(scores[i]), chunks[i]) for i in order]


if __name__ == "__main__":
    for m in sys.argv[1:] or MODELS:
        chunks, v = index(m)
        print(f"{m}: {v.shape[0]} chunks x {v.shape[1]} dims")
