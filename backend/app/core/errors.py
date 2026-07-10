"""Domain exceptions shared across services.

Raise these from the service layer so both workstreams (extraction, form-fill)
signal failures consistently. `main.py` maps `AppError` to a JSON response.
"""


class AppError(Exception):
    """Base for application-level errors. `status_code` drives the HTTP response."""

    status_code: int = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LLMError(AppError):
    """An LLM call failed (auth, timeout, malformed response, etc.)."""

    status_code = 502


class ExtractionError(AppError):
    """Document extraction (stream 2) failed."""

    status_code = 422


class FormFillError(AppError):
    """Browser automation / form population (stream 3) failed."""

    status_code = 502
