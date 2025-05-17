class BaseNXError(Exception):
    """Base class for all exceptions raised by the NX library."""

    status = 500

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail)
        if detail is not None:
            self.detail = detail


class NotFoundError(BaseNXError):
    status = 404
    detail = "Not Found"


class UnauthorizedError(BaseNXError):
    status = 401
    detail = "Unauthorized"
