# Alma — Document Upload Platform

Upload passport and G-28 documents (PDF / JPEG / PNG), store them with metadata,
and expose the data model that later powers **data extraction** and **form
population**. This repository implements the foundation: the upload interface,
the database layer, and a fully Dockerized deployment. Extraction and
browser-automation form-fill are scaffolded as service interfaces so they can be
implemented without reworking the schema or the API.

## Architecture

Three containers, single origin (nginx proxies `/api` to the backend, so there
is no CORS to configure):

```
Browser ──▶ web (nginx: React build + /api proxy) ──▶ api (FastAPI) ──▶ db (Postgres)
                                                          │
                                                          └──▶ uploads volume (files on disk)
```

- **web** — React (Vite) SPA served by nginx on port **8080**.
- **api** — FastAPI on port **8000**; runs Alembic migrations on startup.
- **db** — Postgres 16.
- Uploaded files live on the `uploads` volume; the DB stores metadata + paths.

### Data model

| Table                | Purpose                                                        |
| -------------------- | ------------------------------------------------------------- |
| `applications`       | Groups the documents (passport + G-28) for one form-fill run. |
| `documents`          | A logical document; `doc_type` = `passport` \| `g28`.         |
| `document_files`     | The uploaded files/pages of a document (many per document).   |
| `extraction_results` | One JSONB result per document (filled by extraction, step 2). |

A passport photographed as several JPGs — or a multi-page G-28 saved as several
PNGs — is **one `documents` row with many `document_files` rows**. A multi-page
PDF is a single file.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- **App UI:** http://localhost:8080
- **API docs (Swagger):** http://localhost:8000/docs  (or http://localhost:8080/api/docs)

## API

| Method   | Path                                  | Description                                |
| -------- | ------------------------------------- | ------------------------------------------ |
| `POST`   | `/api/documents`                      | Upload one or many files as one document.  |
| `POST`   | `/api/documents/{id}/files`           | Append more files/pages to a document.     |
| `GET`    | `/api/documents`                      | List documents with status + file counts.  |
| `GET`    | `/api/documents/{id}`                 | Document detail incl. files and extraction. |
| `GET`    | `/api/documents/{id}/files/{file_id}` | Stream a stored file.                      |
| `DELETE` | `/api/documents/{id}/files/{file_id}` | Remove a mistakenly-added page.            |
| `GET`    | `/api/applications`                   | List applications (cases).                  |
| `GET`    | `/api/applications/{case_id}`         | Case documents + merged, fill-ready data.   |
| `GET`    | `/api/health`                         | Liveness + DB check.                        |

`POST /api/documents` is `multipart/form-data` with `doc_type`, one or more
`files`, and an optional `case_id`. Each file is validated by **magic bytes**
(not the client-supplied content type) and against the `MAX_UPLOAD_MB` limit.

### Cases and the extraction → automation seam

An optional **Case ID** entered at upload groups a passport + G-28 under one
application (get-or-create). `GET /api/applications/{case_id}` returns the merged
extraction data keyed by document type — `{"passport": {...}, "g28": {...}}` —
which is what the form-fill step consumes.

The design is **form-agnostic**: extraction stores whatever keys the LLM finds
(loose JSONB, no fixed field list). At fill time the LLM is given **two sets of
dict keys** — the extracted-data keys and the target form's field keys — and
generates the mapping between them. Neither side is tied to a specific form or
schema.

## Configuration

All settings are read from the environment / `.env` (see `.env.example`).
Changing a value is `.env`-only; the fields are declared once in
`backend/app/config.py`. Notable keys: `ANTHROPIC_API_KEY`, `LLM_MODEL`,
`FORM_URL`, `BROWSER_HEADLESS`. Secrets live in `.env` (gitignored).

## Testing it end-to-end

1. Upload a passport as **two JPGs at once** and a G-28 as a PDF via the UI.
2. Confirm the passport appears as one document with **2 files**, and both move
   `uploaded` → `extracted` (a placeholder result until step 2 is implemented).
3. Try an unsupported file (e.g. `.txt`) or an oversized file → expect a clear
   `400` / `413` error.
4. `docker compose down && docker compose up` → documents persist (Postgres
   volume) and files remain downloadable (uploads volume).
5. Inspect the DB: `docker compose exec db psql -U alma -d alma -c '\dt'`.

## Next phases (scaffolded, not implemented)

Shared plumbing both streams use is in place: a provider-agnostic LLM client
(`backend/app/services/llm.py`, `get_llm_client()`), `session_scope()` for
out-of-request DB work, structured logging (`app/core/logging.py`), and domain
errors (`app/core/errors.py`).

- **Data extraction** — `backend/app/services/extraction.py`. The upload flow
  already drives `extracting → extracted/failed` and persists an
  `ExtractionResult`; stream 2 replaces `_extract` with real vision-LLM logic
  (read a document's files via `storage.read_file`, pass as attachments to
  `get_llm_client().complete_json(...)`).
- **Form population** — `backend/app/services/form_fill.py`, run in the
  **`automation`** container (`automation/Dockerfile`, Playwright preinstalled).
  It consumes `build_application_data(application)` and uses the LLM to map keys
  to form fields. Import-safe: Playwright is imported lazily so the `api` image
  needs no browser deps.

```bash
# Build the Playwright worker image (not started by default):
docker compose --profile worker build automation
```

## Running without Docker (optional)

Backend:

```bash
cd backend
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://alma:alma@localhost:5432/alma
export UPLOAD_DIR=./data/uploads
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend (proxies `/api` to `http://localhost:8000`):

```bash
cd frontend
npm install
npm run dev
```
