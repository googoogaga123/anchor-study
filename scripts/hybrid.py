"""Phase 6: hybrid search - keyword + vector, merged by RRF, then reranked.

  1. Candidates   up to CANDIDATES chunks from each search (store.py).
  2. RRF          Reciprocal Rank Fusion: each chunk scores the sum, over the
                  searches that found it, of 1 / (RRF_K + its rank there).
                  Only ranks count, so a keyword score and a cosine score -
                  different scales - never have to be compared. RRF_K = 60 is
                  the constant from the original RRF paper.
  3. Rerank       the self-hosted cross-encoder bge-reranker-v2-m3 reads the
                  question and each candidate together and scores how well
                  that chunk answers it. The top k go to the answering model.

The plan says "rerank the top ~150 to 20"; with the eval Library's 25 chunks
every chunk is a candidate, and k = 5 (record in makendra.md, phase 5).
"""
import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import embed  # noqa: E402
import store  # noqa: E402

CANDIDATES = 150
RRF_K = 60
RERANKER = "BAAI/bge-reranker-v2-m3"
_reranker = None
_lock = threading.Lock()  # score.py runs questions in parallel threads


def rrf(*ranked_lists):
    scores, by_id = {}, {}
    for hits in ranked_lists:
        for rank, h in enumerate(hits, 1):
            scores[h["chunk_id"]] = scores.get(h["chunk_id"], 0.0) + 1.0 / (RRF_K + rank)
            by_id[h["chunk_id"]] = h
    return [by_id[cid] | {"rrf": s} for cid, s in sorted(scores.items(), key=lambda kv: -kv[1])]


def rerank(question, candidates):
    global _reranker
    with _lock:
        if _reranker is None:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANKER)
        scores = _reranker.predict([(question, embed.chunk_input(c)) for c in candidates], batch_size=8)
    return [c | {"rerank": float(s)} for c, s in sorted(zip(candidates, scores), key=lambda cs: -cs[1])]


def search(question, k, library=store.LIBRARY):
    """Top k chunks for a question, best first, with the scores of each stage."""
    fused = rrf(store.keyword(question, CANDIDATES, library), store.vector(question, CANDIDATES, library))
    return rerank(question, fused[:CANDIDATES])[:k]
