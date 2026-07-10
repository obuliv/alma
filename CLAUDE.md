# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A document-upload platform for passport and G-28 documents (PDF/JPEG/PNG). This
repo implements the **foundation** (upload interface, database layer, Dockerized
deployment) plus **data extraction** (step 2, `backend/app/services/extraction.py`).
One later phase remains a stub so it slots in without schema/API rework:

- **Form population** via browser automation (step 3) — `backend/app/services/form_fill.py`

When implementing that, fill in the existing stub methods; do not restructure
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

### Extraction pipeline (`backend/app/services/extraction.py`)

Every document is reduced to text, then one `complete_json` call turns the text
into the flat, form-agnostic `data` dict (no fixed field list — see "The seam"
above). Per file, `_file_to_text`:
1. PDF → try the embedded text layer (`app/services/text_extraction.py`,
   pypdfium2). Used as-is if it clears a min-length threshold.
2. Otherwise (scanned PDF or image upload) → the configured OCR engine
   (`app/services/ocr.py::get_ocr_engine()`, selected by `OCR_MODE`) turns page
   images into text: `llm` (default) sends them to Claude vision via
   `LLMClient.complete_vision`; `rapidocr` runs local PP-OCR models
   (`rapidocr-onnxruntime`, no external call — model weights auto-download on
   first use).

`raw_text` is always persisted on `ExtractionResult`, regardless of which path
produced it. The doc-type → system-prompt lookup (`_SYSTEM_PROMPTS`) has no
fallback — an unrecognized `doc_type` raises immediately rather than silently
extracting with the wrong template; this is safe today because the API layer
(`_parse_doc_type`) already only accepts values in the `DocType` enum.

For PDFs, `text_extraction.form_field_text` (via `pypdf`) always merges in
filled AcroForm field values on top of whatever the text-layer/OCR step
produced. This matters because a fillable PDF's answers live in form-field
widgets, not the page's text content stream — a G-28 filled out in a PDF
editor has plenty of text-layer content (the blank template's printed
labels) but zero actual data in it, so without this step extraction silently
returns `{}` even though `has_text_layer` passes. Field values are read by
walking each page's `/Annots` rather than `PdfReader.get_fields()`/the
`/AcroForm` field tree — some real-world PDFs have a malformed field tree
that makes the latter miss most fields.

Checkbox/radio widgets (`/FT == "/Btn"`) are called out as `name: true`/
`name: false` lines — always, checked or not, unlike text fields which are
omitted when empty — and the system prompts (`_FORM_FIELD_BOOLEAN_NOTE`)
tell the LLM to render these as JSON booleans. This is deliberate: it's the
only place in `extraction_results.data` where a value's Python type
(`bool`) carries meaning, so stream 3's mapper can detect "this extracted
field is a checkbox" without any fixed schema. OCR-derived text has no
equivalent — a scanned form's checkbox marks stay as whatever plain text
the OCR/vision engine transcribes; only the AcroForm path gets this
treatment for now.

Gotcha: `rapidocr-onnxruntime` hard-depends on `opencv-python` (not
`-headless`), which needs `libGL`/`libglib` — pinning the headless variant
alongside it doesn't help, since pip won't dedupe two differently-named
packages that both provide `cv2`. The Dockerfile installs `libgl1
libglib2.0-0` instead of fighting this.

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
