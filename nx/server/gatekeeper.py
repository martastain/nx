import contextlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from nx.exceptions import UnauthorizedError
from nx.objects.user import User


async def authenticate_api_key(api_key: str) -> User:
    if api_key == "valid_api_key":
        return await User.by_name("admin")
    raise UnauthorizedError("Invalid api key")


async def authenticate_session(session_id: str) -> User:
    if session_id == "valid_session":
        return await User.by_name("admin")
    raise UnauthorizedError("Invalid session")


async def authenticate(request: Request) -> User:
    with contextlib.suppress(UnauthorizedError):
        if api_key := request.headers.get("x-api-key"):
            return await authenticate_api_key(api_key)
    if session_id := request.cookies.get("session_id"):
        return await authenticate_session(session_id)
    raise UnauthorizedError


class GatekeeperMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        context = {}
        try:
            user = await authenticate(request)
            context["user"] = user.name
            request.state.user = user
            request.state.unauthorized_reason = None
        except UnauthorizedError as e:
            request.state.user = None
            request.state.unauthorized_reason = str(e)

        return await call_next(request)
