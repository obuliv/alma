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
| `GET`    | `/api/health`                         | Liveness + DB check.                        |

`POST /api/documents` is `multipart/form-data` with `doc_type` and one or more
`files`. Each file is validated by **magic bytes** (not the client-supplied
content type) and against the `MAX_UPLOAD_MB` limit.

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

- **Data extraction** — `backend/app/services/extraction.py`. The upload flow
  already drives `extracting → extracted/failed` and persists an
  `ExtractionResult`; step 2 replaces `_extract` with real OCR/LLM logic that
  reads a document's files and returns the structured `data` fields.
- **Form population** — `backend/app/services/form_fill.py`. Entry point for
  browser automation (e.g. Playwright) against the target form URL.

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
