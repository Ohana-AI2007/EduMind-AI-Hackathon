"""Application exceptions mapped to JSON error responses in main.py."""


class EduMindError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AIConfigError(EduMindError):
    status_code, code = 503, "ai_not_configured"


class AIServiceError(EduMindError):
    status_code, code = 502, "ai_service_error"


class NotFoundError(EduMindError):
    status_code, code = 404, "not_found"


class BadRequestError(EduMindError):
    status_code, code = 400, "bad_request"


class PayloadTooLargeError(EduMindError):
    status_code, code = 413, "payload_too_large"


class UnprocessableError(EduMindError):
    status_code, code = 422, "unprocessable"


class RateLimitError(EduMindError):
    status_code, code = 429, "rate_limited"


class ExtractionError(EduMindError):
    status_code, code = 422, "extraction_failed"