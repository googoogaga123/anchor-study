"""The website's own tables, in the same Postgres as the chunks (database `ailodge`).

  users     one row per signed-up user: role owner | admin | member, their
            Library id, and what they have used against their limits
  files     the files in each Library (versions kept when "keep both")
  messages  chat history per user (question, answer JSON)
  spend     every model call's tokens and estimated cost, against the Demo budget

Limits (build plan, Website step; glossary):
  Member  1 file ever, at most 50 pages; 3 questions ever. An Admin can reset either.
  Admin   at most 3 (owner included); no question limit; 200 pages of uploads.
  Owner   the one Admin who can promote others.
"""
import os

import psycopg
from psycopg.rows import dict_row

MEMBER_FILES, MEMBER_PAGES, MEMBER_QUESTIONS = 1, 50, 3
ADMIN_PAGES, MAX_ADMINS = 200, 3
DEMO_BUDGET_USD = float(os.environ.get("DEMO_BUDGET_USD", "1.00"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              serial PRIMARY KEY,
    email           text UNIQUE NOT NULL,
    name            text,
    role            text NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    library_id      text UNIQUE NOT NULL,
    questions_used  int NOT NULL DEFAULT 0,
    files_used      int NOT NULL DEFAULT 0,
    pages_used      int NOT NULL DEFAULT 0,
    created         timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS files (
    id          serial PRIMARY KEY,
    user_id     int NOT NULL REFERENCES users(id),
    library_id  text NOT NULL,
    name        text NOT NULL,          -- the name chunks cite
    label       text,                   -- "uploaded 18 Oct" when a same-name version is kept
    format      text NOT NULL,
    pages       int NOT NULL,
    path        text NOT NULL,          -- the stored file, relative to the repo
    status      text NOT NULL DEFAULT 'ready',   -- processing | ready | failed
    error       text,
    created     timestamptz NOT NULL DEFAULT now()
);
-- Signed in through the login service with a verified smu.edu.sg email (auth.py): free plan.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_smu boolean NOT NULL DEFAULT false;
-- Uploads (ingest.py): what processing is doing now, and the readable copy citations open.
ALTER TABLE files ADD COLUMN IF NOT EXISTS progress text;
ALTER TABLE files ADD COLUMN IF NOT EXISTS parsed text;
CREATE TABLE IF NOT EXISTS messages (
    id       serial PRIMARY KEY,
    user_id  int NOT NULL REFERENCES users(id),
    question text NOT NULL,
    answer   jsonb NOT NULL,
    created  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS spend (
    id          serial PRIMARY KEY,
    user_id     int REFERENCES users(id),
    kind        text NOT NULL,          -- answer | upload
    tokens_in   int NOT NULL,
    tokens_out  int NOT NULL,
    usd         numeric(10, 6) NOT NULL,
    created     timestamptz NOT NULL DEFAULT now()
);
"""


def connect():
    # WEB_PGDATABASE keeps the website's tables apart when testing (the chunks
    # stay in PGDATABASE, default "ailodge").
    name = os.environ.get("WEB_PGDATABASE") or os.environ.get("PGDATABASE", "ailodge")
    return psycopg.connect(dbname=name, autocommit=True, row_factory=dict_row)


def init():
    with connect() as conn:
        conn.execute(SCHEMA)
        # A file still 'processing' when the server starts was cut off by a restart.
        conn.execute("UPDATE files SET status = 'failed', progress = NULL, error = 'Stopped by a server restart - please upload it again.' "
                     "WHERE status = 'processing'")


def one(sql, args=()):
    with connect() as conn:
        return conn.execute(sql, args).fetchone()


def all_(sql, args=()):
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


def run(sql, args=()):
    with connect() as conn:
        conn.execute(sql, args)


def spent_usd():
    return float(one("SELECT coalesce(sum(usd), 0) AS s FROM spend")["s"])


def budget_left():
    return DEMO_BUDGET_USD - spent_usd()
