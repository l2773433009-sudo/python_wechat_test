class WcfLinkClientError(Exception):
    """Base exception for the Python wcfLink client."""


class WcfLinkAPIError(WcfLinkClientError):
    """Raised when the wcfLink HTTP API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str, body: object | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
