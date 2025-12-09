class Error(Exception):
    """Base class for all exceptions raised by the NX library."""

    status = 500

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail)
        if detail is not None:
            self.detail = detail


class NotFoundError(Error):
    status = 404
    detail = "Not Found"


class UnauthorizedError(Error):
    status = 401
    detail = "Unauthorized"


class BadRequestError(Error):
    status = 400
    detail = "Bad Request"


class ForbiddenError(Error):
    status = 403
    detail = "Forbidden"


class ConflictError(Error):
    status = 409
    detail = "Conflict"
