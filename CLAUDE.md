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
the models or upload flow around them. Shared plumbing both streams depend on is
already built — reuse it (see "Shared utils & the seam" below).

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
- `extraction_results` — one row per document, `data` is **JSONB** holding
  whatever keys the LLM extracts (form-agnostic, no fixed field list).
- `applications.case_id` — human-entered Case ID (optional at upload). Groups a
  passport + G-28 into one application so form-fill can select data by case.

Enums are stored as plain strings validated in Python (see the `enum.Enum`
classes in the model files), not Postgres enum types — keeps migrations simple.

### Shared utils & the seam (how the two streams connect)

Built and meant for reuse — do not re-invent these in the workstreams:

- `app/services/llm.py` — provider-agnostic `LLMClient` (ABC) + `AnthropicLLMClient`,
  via `get_llm_client()` (selected by `settings.llm_provider`). `complete_json(...,
  attachments=[(bytes, media_type)])` serves **both** vision extraction (stream 2)
  and text field-mapping (stream 3). Failures raise `LLMError`.
- `app/database.py::session_scope()` — transactional session for out-of-request
  work (background tasks, the automation worker). Commits/rolls back/closes.
- `app/core/logging.py` (`configure_logging`/`get_logger`) and
  `app/core/errors.py` (`AppError` + `ExtractionError`/`FormFillError`/`LLMError`,
  mapped to JSON by a handler in `main.py`).

**The seam:** extraction writes loose-JSONB `extraction_results.data` with
whatever keys the LLM finds (form-agnostic — no fixed vocabulary). Grouping is by
`case_id`. Automation's input is `application_service.build_application_data()`,
which merges each doc's data into `{"passport": {...}, "g28": {...}}`. At fill
time the LLM is given **two key-sets** — the extracted-data keys and the scraped
form's field keys — and generates the mapping between them. This is why the JSONB
stays untyped and nothing is tied to a specific form.

### Upload flow (`backend/app/api/routes/documents.py`)

`POST /api/documents` (multipart: `doc_type` + one-or-many `files` + optional
`case_id`) creates one `documents` row + N `document_files`, then fires
extraction **once** as a FastAPI `BackgroundTask`. Key detail: the background
task uses `session_scope()` (`_run_extraction`) rather than the request-scoped
`get_db` session, which is already closed by the time it runs.

Every uploaded file is validated by **magic bytes**, not the client-supplied
content type — `app/core/validation.py` uses `filetype.guess()` and returns the
canonical content type we store. A renamed `.txt` is rejected with 400.

Migrations run automatically on container start (the api `CMD` runs
`alembic upgrade head` before uvicorn).

### Browser-automation worker (stream 3)

`form_fill.py` runs in a **separate `automation` container**
(`automation/Dockerfile`, Playwright base image) under the compose `worker`
profile — it is not started by `docker compose up`. This keeps heavy browser
deps out of the `api` image, so `form_fill.py` imports Playwright **lazily**
inside `fill()`; never add a top-level `playwright` import (it would break the
api image). Build it with `docker compose --profile worker build automation`.

Minimal React SPA. `api/client.ts` is the single fetch wrapper (same-origin
`/api`). `DocumentList.tsx` **polls** `GET /api/documents` every 2.5s so status
transitions (uploaded → extracted) appear without a reload — there are no
websockets. `UploadForm.tsx` uses `<input multiple>` for the multi-file case.

## Conventions

- Migrations here are **hand-written** to match the models (see
  `alembic/versions/0001_initial.py`), and `alembic/env.py` reads the URL from
  `app.config.settings`. When you change a model, generate a migration with
  `--autogenerate` and review it.
- Config is centralized in `app/config.py` (pydantic-settings), read from env /
  `.env`. Changing a value is `.env`-only; **adding** a knob means declaring the
  field once here (with a default), then surfacing it in `.env.example` +
  `docker-compose.yml`. Never scatter `os.getenv` calls.
- The DB is treated as **disposable** in dev — `case_id` was folded into
  `0001_initial` rather than added as a new migration. Recreate with
  `docker compose down -v && up`.
