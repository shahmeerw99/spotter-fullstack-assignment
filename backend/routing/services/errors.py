class ServiceError(Exception):
    """An error with an HTTP status and a message that is safe to show to the user."""

    status = 500

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class BadInput(ServiceError):
    status = 400


class NotFound(ServiceError):
    status = 404


class Unprocessable(ServiceError):
    status = 422


class UpstreamError(ServiceError):
    status = 502


class UpstreamTimeout(ServiceError):
    status = 504
