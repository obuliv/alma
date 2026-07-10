# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A document-upload platform for passport and G-28 documents (PDF/JPEG/PNG). This
repo implements the **foundation**: upload interface, database layer, and
Dockerized deployment. Two later phases are intentionally left as stubs so they
slot in without schema/API rework:

- **Data extraction** (step 2) — `backend/app/services/extraction.py`
- **Form population** via browser automation (step 3) — `backend/app/services/form_fill.py`

When implementing those, fill in the existing stub methods; do not restructure
the models or upload flow around them.

## Commands

```bash
# Run the whole stack (db + api + web)
cp .env.example .env
docker compose up --build          # UI :8080, API :8000, Swagger :8000/docs

docker compose down                # stop (keeps pgdata + uploads volumes)
docker compose down -v             # stop AND wipe DB + uploaded files

# Backend outside Docker (needs a reachable Postgres)
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://alma:alma@localhost:5432/alma
export UPLOAD_DIR=./data/uploads
alembic upgrade head               # apply migrations
uvicorn app.main:app --reload

# New migration after changing app/models/*
alembic revision --autogenerate -m "describe change"

# Frontend outside Docker (proxies /api -> localhost:8000 via vite.config.ts)
cd frontend
npm install
npm run dev
npm run build                      # tsc typecheck + vite build
```

There is no test suite yet. To smoke-test the API, use Swagger at
`http://localhost:8000/docs` or `curl` against `/api/*`.

## Architecture

Three containers, **single origin**: nginx in the `web` container serves the
React build and reverse-proxies `/api/` to `api:8000` (see
`frontend/nginx.conf`). This is why there is no CORS config in the normal path —
`app/config.py` only wires CORS when `CORS_ORIGINS` is set, which is for running
the frontend dev server separately.

```
Browser -> web (nginx: SPA + /api proxy) -> api (FastAPI) -> db (Postgres)
                                              |
                                              +-> uploads volume (files on disk)
```

Files are written to disk on the `uploads` volume (`app/services/storage.py`,
under `UPLOAD_DIR/<document_id>/`); the DB stores only metadata + paths, never
blobs.

### Data model (`backend/app/models/`)

The central modeling decision: **one logical document can have many files.** A
passport photographed as several JPGs, or a multi-page G-28 as several PNGs, is
a single `documents` row with N `document_files` rows. A multi-page PDF is one
file. Preserve this split when extending — extraction reads all of a document's
files and produces one merged result.

- `applications` — groups the documents (passport + G-28) that feed one
  form-fill run. Nullable on `documents` for now; exists so step 3's form-fill
  (which needs both docs together) won't require a later migration.
- `documents` — logical doc; `doc_type` ∈ {`passport`, `g28`}, `status` drives
  the lifecycle `uploaded → extracting → extracted | failed`.
- `document_files` — the actual uploaded pages, ordered by `page_order`.
- `extraction_results` — one row per document, `data` is **JSONB** so step 2 can
  change the field set without a migration. `ExtractionService.EXPECTED_FIELDS`
  documents the target schema.

Enums are stored as plain strings validated in Python (see the `enum.Enum`
classes in the model files), not Postgres enum types — keeps migrations simple.

### Upload flow (`backend/app/api/routes/documents.py`)

`POST /api/documents` (multipart: `doc_type` + one-or-many `files`) creates one
`documents` row + N `document_files`, then fires extraction **once** as a
FastAPI `BackgroundTask`. Key detail: the background task opens its **own**
`SessionLocal` (`_run_extraction`) because the request-scoped `get_db` session is
already closed by the time it runs.

Every uploaded file is validated by **magic bytes**, not the client-supplied
content type — `app/core/validation.py` uses `filetype.guess()` and returns the
canonical content type we store. A renamed `.txt` is rejected with 400.

Migrations run automatically on container start (the api `CMD` runs
`alembic upgrade head` before uvicorn).

### Frontend (`frontend/src/`)

Minimal React SPA. `api/client.ts` is the single fetch wrapper (same-origin
`/api`). `DocumentList.tsx` **polls** `GET /api/documents` every 2.5s so status
transitions (uploaded → extracted) appear without a reload — there are no
websockets. `UploadForm.tsx` uses `<input multiple>` for the multi-file case.

## Conventions

- Migrations here are **hand-written** to match the models (see
  `alembic/versions/0001_initial.py`), and `alembic/env.py` reads the URL from
  `app.config.settings`. When you change a model, generate a migration with
  `--autogenerate` and review it.
- Config is centralized in `app/config.py` (pydantic-settings). Add new tunables
  there and surface them in `.env.example` + `docker-compose.yml`, not as
  scattered `os.getenv` calls.
