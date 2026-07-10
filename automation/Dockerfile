# Browser-automation worker image (stream 3). Ships Playwright + browsers so the
# form-fill logic can drive a real browser. Reuses the backend app package
# (models, config, LLM client, application_service) — built from the repo root.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Backend deps (SQLAlchemy, anthropic, etc.) + the Playwright Python package
# pinned to match the browsers preinstalled in this base image (v1.49.0).
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright==1.49.0

# Reuse the backend application code.
COPY backend/ .

# Placeholder — stream 3 replaces this with the worker entrypoint that reads an
# application by case_id, maps fields via the LLM, and fills the form.
CMD ["python", "-c", "print('automation worker scaffold — implement stream 3 (form_fill)')"]
