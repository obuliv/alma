# Alma — Document Upload Platform

Upload passport and G-28 documents (PDF / JPEG / PNG), store them with metadata,
and expose the data model that later powers **data extraction** and **form
population**. This repository implements the foundation: the upload interface,
the database layer, and native (no-Docker) local dev tooling. Extraction and
browser-automation form-fill are scaffolded as service interfaces so they can be
implemented without reworking the schema or the API.

## Architecture

Two local processes, same-origin in the browser (the Vite dev server proxies
`/api` to the backend, so there's no CORS to configure):

```
Browser ──▶ Vite dev server (React SPA + /api proxy) ──▶ FastAPI ──▶ SQLite file
                                                             │
                                                             └──▶ ./data/uploads (files on disk)
```

- **frontend** — React (Vite) SPA, dev server on port **5173** (Vite's default;
  it prints the exact URL on startup).
- **backend** — FastAPI on port **8000**.
- **db** — SQLite, a single file at `backend/data/alma.db`.
- Uploaded files live under `backend/data/uploads`; the DB stores metadata +
  paths only.

### Data model

| Table                | Purpose                                                        |
| -------------------- | ------------------------------------------------------------- |
| `applications`       | Groups the documents (passport + G-28) for one form-fill run. |
| `documents`          | A logical document; `doc_type` = `passport` \| `g28`.         |
| `document_files`     | The uploaded files/pages of a document (many per document).   |
| `extraction_results` | One JSON result per document (filled by extraction, step 2).  |

A passport photographed as several JPGs — or a multi-page G-28 saved as several
PNGs — is **one `documents` row with many `document_files` rows**. A multi-page
PDF is a single file.

## Quick start

```bash
./run.sh
```

This creates a Python venv under `backend/.venv`, installs backend
dependencies (including Playwright's Chromium, for form-fill), runs
migrations (creating `backend/data/alma.db` on first run), starts the API,
installs frontend dependencies, and starts the Vite dev server — printing its
URL (open that one; it proxies `/api` to the backend for you). Ctrl+C stops
both.

### What the script does, if you'd rather run it by hand

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install playwright==1.49.0 && playwright install chromium  # for form-fill
alembic upgrade head
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev
```

Then open the URL Vite prints (typically http://localhost:5173). API docs
(Swagger) are at http://localhost:8000/docs.

No environment variables are required for a first run — `DATABASE_URL` and
`UPLOAD_DIR` default to `backend/data/alma.db` and `backend/data/uploads`. Copy
`backend/.env.example` to `backend/.env` to set `ANTHROPIC_API_KEY` or override
any other setting.

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
(loose JSON, no fixed field list). At fill time the LLM is given **two sets of
dict keys** — the extracted-data keys and the target form's field keys — and
generates the mapping between them. Neither side is tied to a specific form or
schema.

## Configuration

All settings are read from the environment / `backend/.env` (see
`backend/.env.example`). Changing a value is `.env`-only; the fields are
declared once in `backend/app/config.py`. Notable keys: `ANTHROPIC_API_KEY`,
`LLM_MODEL`, `FORM_URL`, `BROWSER_HEADLESS`. Secrets live in `backend/.env`
(gitignored).

## Testing it end-to-end

1. Upload a passport as **two JPGs at once** and a G-28 as a PDF via the UI.
2. Confirm the passport appears as one document with **2 files**, and both move
   `uploaded` → `extracted` (needs `ANTHROPIC_API_KEY` set to run real
   extraction).
3. Try an unsupported file (e.g. `.txt`) or an oversized file → expect a clear
   `400` / `413` error.
4. Stop the API (Ctrl+C) and restart it (`./run.sh` or `uvicorn ...` again) →
   documents persist (`backend/data/alma.db`) and files remain downloadable
   (`backend/data/uploads`).
5. Inspect the DB: `sqlite3 backend/data/alma.db ".tables"` or
   `sqlite3 backend/data/alma.db "select * from documents;"`.

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
- **Form population** — `backend/app/services/form_fill.py`. It consumes
  `build_application_data(application)` and uses the LLM to map keys to form
  fields, then drives a **headed** (visible) Playwright browser — run it from
  a process with a display (your machine via `uvicorn`), not headless CI.

## Resetting the database

SQLite is treated as disposable in dev: delete `backend/data/alma.db` (and
`backend/data/uploads` for a clean upload dir too), then re-run
`alembic upgrade head` (or `./run.sh`, which runs migrations every time it
starts).
