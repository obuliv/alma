# Alma — Document Upload, Extraction & Form Fill

Upload passport and G-28 documents (PDF / JPEG / PNG), extract their data with
an LLM, and use that data to auto-fill an immigration form in a real browser
you can review and submit yourself. The repository has three parts, all
implemented:

1. **Foundation** — upload interface, database layer, native (no-Docker)
   local dev via `./run.sh`.
2. **Data extraction** — `backend/app/services/extraction.py` turns uploaded
   files into structured JSON via a vision-capable LLM (+ MRZ checksum
   validation for passports).
3. **Form population** — `backend/app/services/form_fill.py` scrapes a target
   form's fields, asks the LLM to map extracted data onto them, and drives a
   **visible** Playwright browser so you can watch, correct, and submit.

## Architecture

Two local processes, same-origin in the browser (the Vite dev server proxies
`/api` to the backend, so there's no CORS to configure):

```
Browser ──▶ Vite dev server (React SPA + /api proxy) ──▶ FastAPI ──▶ SQLite file
                                                             │    │
                                                             │    └──▶ ./data/uploads (files on disk)
                                                             │
                                                             └──▶ Anthropic API (extraction + field mapping)
                                                             │
                                                             └──▶ Playwright ──▶ headed Chromium ──▶ target form URL
```

- **frontend** — React (Vite) SPA, dev server on port **5173** (Vite's
  default; it prints the exact URL on startup). Two tabs: **Documents**
  (upload + status) and **Form Fill** (pick a case + form URL, watch runs).
  Both lists poll their endpoints every 2.5s — no websockets.
- **backend** — FastAPI on port **8000**.
- **db** — SQLite, a single file at `backend/data/alma.db`.
- Uploaded files live under `backend/data/uploads`; the DB stores metadata +
  paths only, never blobs.

### Data model

| Table                 | Purpose                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------ |
| `applications`         | Groups the documents (passport + G-28) for one form-fill run, keyed by `case_id`. |
| `documents`             | A logical document; `doc_type` = `passport` \| `g28`; `status` = `uploaded → extracting → extracted \| failed`. |
| `document_files`        | The uploaded files/pages of a document (many per document), ordered by `page_order`. |
| `extraction_results`    | One JSON row per document — form-agnostic, whatever keys the LLM extracts.         |
| `form_fill_runs`        | One row per form-fill attempt: `form_url`, `status` (`filling → filled \| failed`), scraped `fields`, applied `mapping`, `error`. |

A passport photographed as several JPGs — or a multi-page G-28 saved as
several PNGs — is **one `documents` row with many `document_files` rows**. A
multi-page PDF is a single file.

### The extraction → form-fill seam

An optional **Case ID** entered at upload groups a passport + G-28 under one
`applications` row (get-or-create). Extraction stores **loose JSON** per
document — whatever keys the LLM finds, no fixed field list — because the
system is form-agnostic by design. `GET /api/applications/{case_id}` merges
each document's data into `{"passport": {...}, "g28": {...}}` via
`application_service.build_application_data()`.

At form-fill time, `form_fill_service.fill()`:
1. Scrapes the target form's field selectors/labels with Playwright.
2. Sends the LLM **two key-sets** — the extracted-data keys and the scraped
   form's field keys — and asks it to generate `{selector: value}`.
3. Fills a **headed** (visible) Chromium window with that mapping and blocks,
   holding the browser open, until you close it — review/correction happens
   live in the browser, not in the UI.

Nothing in the schema is tied to a specific form. Checkboxes are the one
place a value's Python type carries meaning: AcroForm checkbox widgets are
extracted as `name: true/false` booleans so the mapper can detect "this is a
checkbox" without a fixed schema.

### Extraction pipeline

Each document's files are reduced to text, then one LLM call produces the
flat `data` dict:

1. PDF → try the embedded text layer (pypdfium2); used as-is if it clears a
   min length threshold.
2. Otherwise (scanned PDF or image) → OCR via `OCR_MODE`: `llm` (default,
   Claude vision) or `rapidocr` (local PP-OCR, no external call).
3. For PDFs, filled AcroForm field values are always merged in on top (walked
   via each page's `/Annots`) — this is what makes a PDF-editor-filled G-28
   extract real data instead of just the blank template's printed labels.
4. For passports, the MRZ (machine-readable zone) is independently parsed and
   checksum-validated (`app/services/mrz.py`) and overlays the LLM's read for
   `surname`/`given_names`/`passport_number`/`nationality`/`date_of_birth`/
   `sex`/`date_of_expiry` whenever the checksum passes — fails open (no MRZ
   found or a bad checksum just leaves the LLM's values in place).

## Quick start

```bash
./run.sh
```

This creates a Python venv under `backend/.venv`, installs backend
dependencies + Playwright's Chromium, runs migrations (creating
`backend/data/alma.db` on first run), starts the API, installs frontend
dependencies, and starts the Vite dev server — printing its URL. Ctrl+C stops
both.

Set `ANTHROPIC_API_KEY` first (see Configuration below) if you want real
extraction and form-fill instead of runs that end in `failed`.

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

**Form-fill opens a visible browser window**, so it needs a process with a
display — run it via `./run.sh` or `uvicorn` directly on your machine (not a
headless CI box).

## Configuration

All settings are read from the environment / `backend/.env`. Copy
`backend/.env.example` to `backend/.env` to set them; no env vars are
required for a first run (`DATABASE_URL`/`UPLOAD_DIR` default to
`backend/data/alma.db`/`backend/data/uploads`). Adding a new setting means
declaring it once in `backend/app/config.py`, then surfacing it in
`backend/.env.example` — never scatter `os.getenv` calls.

| Key                  | Purpose                                                             |
| --------------------- | ---------------------------------------------------------------------- |
| `MAX_UPLOAD_MB`        | Per-file upload size limit (default `10`).                          |
| `LLM_PROVIDER`         | `anthropic` (only provider wired up today).                          |
| `ANTHROPIC_API_KEY`    | Required for real extraction + form-field mapping.                   |
| `LLM_MODEL`            | Model used for extraction and mapping calls.                         |
| `OCR_MODE`             | `llm` (Claude vision, default) or `rapidocr` (local, no API call).    |
| `FORM_URL`             | Default form URL pre-filled in the Form Fill tab.                     |
| `BROWSER_HEADLESS`     | Should stay `false` in normal use — see "opens a visible browser" above. |
| `BROWSER_TIMEOUT_MS`   | Playwright navigation/action timeout.                                  |

`OCR_MODE=rapidocr` on Linux needs `libgl1 libglib2.0-0` installed (macOS
ships these already) — `rapidocr-onnxruntime` hard-depends on
`opencv-python` for these.

## API

| Method   | Path                                   | Description                                |
| -------- | ---------------------------------------- | --------------------------------------------- |
| `POST`   | `/api/documents`                         | Upload one or many files as one document (`doc_type`, `files`, optional `case_id`). Fires extraction as a background task. |
| `POST`   | `/api/documents/{id}/files`              | Append more files/pages to a document.        |
| `GET`    | `/api/documents`                         | List documents with status + file counts.     |
| `GET`    | `/api/documents/{id}`                    | Document detail incl. files and extraction.   |
| `GET`    | `/api/documents/{id}/files/{file_id}`    | Stream a stored file.                         |
| `DELETE` | `/api/documents/{id}/files/{file_id}`    | Remove a mistakenly-added page.               |
| `GET`    | `/api/applications`                      | List applications (cases).                    |
| `GET`    | `/api/applications/{case_id}`            | Case documents + merged, fill-ready data (`{"passport": {...}, "g28": {...}}`). |
| `POST`   | `/api/form-fill-runs`                    | Start a form-fill run (`case_id`, `form_url`). Scrapes fields, maps data, opens a headed browser as a background task. |
| `GET`    | `/api/form-fill-runs`                    | List form-fill runs with status.              |
| `GET`    | `/api/form-fill-runs/{id}`               | Run detail incl. scraped `fields`, applied `mapping`, `error`. |
| `GET`    | `/api/health`                            | Liveness + DB check.                          |

`POST /api/documents` is `multipart/form-data`. Each file is validated by
**magic bytes** (not the client-supplied content type, via
`filetype.guess()`) and against `MAX_UPLOAD_MB` — a renamed `.txt` is
rejected with `400`.

## Testing

### Automated (unit tests)

```bash
cd backend
source .venv/bin/activate
pytest
```

Currently one pure-logic suite, `backend/tests/test_mrz.py` (MRZ parsing +
checksum validation). There's no automated test suite for the API/UI as a
whole yet — smoke-test via Swagger at http://localhost:8000/docs, `curl`
against `/api/*`, or the manual flow below.

### Manual end-to-end

Requires `ANTHROPIC_API_KEY` set in `backend/.env` for real extraction and
field mapping — without it, extraction and form-fill runs will end in
`failed` rather than silently no-op.

**Upload & extraction**
1. Start the app (`./run.sh`), open the Vite URL, and use the **Documents**
   tab.
2. Upload a passport as **two JPGs at once** and a G-28 (PDF or image) under
   the same **Case ID**.
3. Confirm the passport appears as one document with **2 files**, and both
   move `uploaded` → `extracting` → `extracted` (the list polls every 2.5s).
4. Open a document to inspect its extracted JSON.
5. Negative cases: upload an unsupported file (e.g. `.txt`) → expect a clear
   `400`; upload something over `MAX_UPLOAD_MB` → expect `413`.
6. Restart the API (Ctrl+C, then `./run.sh`/`uvicorn` again) → documents
   persist (`backend/data/alma.db`) and files remain downloadable
   (`backend/data/uploads`).

**Form fill**
1. Once both documents for a case are `extracted`, switch to the **Form
   Fill** tab.
2. Pick the Case ID from the dropdown (populated from `GET
   /api/applications`) and enter a form URL.
3. Submit — a `form_fill_runs` row appears with status `filling`; a
   **visible Chromium window** opens shortly after.
4. Watch the form populate; the browser blocks until you close the window —
   review/correct fields live, then close it yourself.
5. Confirm the run's status becomes `filled` in the **Form Fill Runs** list,
   and that `GET /api/form-fill-runs/{id}` shows the scraped `fields` and
   applied `mapping`.
6. Negative case: use a URL with no recognizable form fields, or an invalid
   URL → expect the run to end in `failed` with an `error` message, not a
   silent hang.

**Inspecting state directly**
```bash
sqlite3 backend/data/alma.db ".tables"
sqlite3 backend/data/alma.db "select id, doc_type, status from documents;"
sqlite3 backend/data/alma.db "select id, status, form_url from form_fill_runs;"
```

## Resetting the database

SQLite is treated as **disposable** in dev: delete `backend/data/alma.db`
(and `backend/data/uploads` for a clean upload dir too), then re-run
`alembic upgrade head` (or `./run.sh`, which runs migrations every time it
starts).
