"""Phase 6: chunks in Postgres, searchable two ways.

One table holds every Library's chunks; every query filters on library_id, so
nothing crosses between users (record 0001). The eval Library is "eval".

  keyword(q, n)  Postgres full-text search: the question's words (stemmed,
                 stop-words dropped) OR-ed together, ranked by ts_rank_cd.
                 OR, not AND: a natural-language question rarely has every
                 word in one chunk. This is "BM25-like" in the plan's words -
                 ts_rank_cd rewards term frequency and closeness, though it is
                 not BM25's exact formula.
  vector(q, n)   pgvector cosine distance on text-embedding-3-small vectors
                 (phase 5's choice), the same vectors as parsed/embeddings/.

    .venv/bin/python scripts/store.py      # (re)load the eval Library

Needs Postgres running with pgvector: brew services start postgresql@18,
database "ailodge" (PGDATABASE overrides).
"""
import os
import pathlib
import sys

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import embed  # noqa: E402

LIBRARY = "eval"
EMBED_MODEL = "3small"
DIMS = 1536

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS chunks (
    library_id text NOT NULL,
    chunk_id   text NOT NULL,
    file       text NOT NULL,
    loc        text,
    heading    text,
    text       text NOT NULL,
    embedding  vector({DIMS}) NOT NULL,
    -- what keyword search reads: the same header + text that is embedded
    tsv        tsvector GENERATED ALWAYS AS (
                   to_tsvector('english', file || ' ' || coalesce(loc, '') || ' ' || text)) STORED,
    PRIMARY KEY (library_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS chunks_tsv ON chunks USING gin (tsv);
"""


def connect():
    conn = psycopg.connect(dbname=os.environ.get("PGDATABASE", "ailodge"), autocommit=True)
    register_vector(conn)
    return conn


def load(library=LIBRARY):
    """Replace a Library's chunks with the current parsed/chunks.jsonl."""
    chunks, vectors = embed.index(EMBED_MODEL)
    with connect() as conn:
        conn.execute(SCHEMA)
        conn.execute("DELETE FROM chunks WHERE library_id = %s", (library,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO chunks (library_id, chunk_id, file, loc, heading, text, embedding)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [(library, c["chunk_id"], c["file"], c.get("loc"), c.get("heading"), c["text"], v)
                 for c, v in zip(chunks, vectors)])
        n = conn.execute("SELECT count(*) FROM chunks WHERE library_id = %s", (library,)).fetchone()[0]
    return n


def _rows(cur):
    return [{"chunk_id": r[0], "file": r[1], "loc": r[2], "heading": r[3], "text": r[4], "score": float(r[5])}
            for r in cur.fetchall()]


def keyword(q, n, library=LIBRARY):
    with connect() as conn:
        cur = conn.execute(
            """
            WITH query AS (
              SELECT to_tsquery('english', array_to_string(
                       tsvector_to_array(to_tsvector('english', %(q)s)), ' | ')) AS tq)
            SELECT chunk_id, file, loc, heading, text, ts_rank_cd(tsv, query.tq) AS score
            FROM chunks, query
            WHERE library_id = %(lib)s AND query.tq <> ''::tsquery AND tsv @@ query.tq
            ORDER BY score DESC, chunk_id
            LIMIT %(n)s
            """, {"q": q, "lib": library, "n": n})
        return _rows(cur)


def vector(q, n, library=LIBRARY):
    qv, _ = embed.embed_texts(EMBED_MODEL, [q])
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT chunk_id, file, loc, heading, text, 1 - (embedding <=> %(v)s) AS score
            FROM chunks WHERE library_id = %(lib)s
            ORDER BY embedding <=> %(v)s, chunk_id
            LIMIT %(n)s
            """, {"v": np.asarray(qv[0]), "lib": library, "n": n})
        return _rows(cur)


if __name__ == "__main__":
    print(f"loaded {load()} chunks into library '{LIBRARY}'")
    for name, fn in (("keyword", keyword), ("vector", vector)):
        hits = fn("Which tool copies the images folder to the EC2 instance?", 3)
        print(name, [(h["chunk_id"], round(h["score"], 3)) for h in hits])
