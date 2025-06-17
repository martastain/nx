import os
import time
import traceback

from shortuuid import ShortUUID
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import nx
from nx.exceptions import BaseNXError


def handle_nx_exception(exc: BaseNXError) -> JSONResponse:
    nx.log.warning(f"{exc.detail}")
    return JSONResponse(
        {
            "status": exc.status,
            "detail": exc.detail,
        },
        status_code=exc.status,
    )


def handle_undhandled_exception(exc: Exception) -> JSONResponse:
    path_prefix = f"{os.getcwd()}/"
    formatted = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    tb = traceback.extract_tb(exc.__traceback__)
    traceback_msg = ""
    for frame in tb[-5:]:
        fpath = frame.filename.split("/")
        for p in ("starlette", "fastapi", "python3.13"):
            if p in fpath:
                break
        else:
            filepath = frame.filename.removeprefix(path_prefix)
            traceback_msg += f"{filepath}:{frame.lineno}\n"
            traceback_msg += f"{frame.line}\n\n"

    traceback_msg = traceback_msg.strip()

    nx.log.error(
        f"Unhandled {formatted}",
        traceback=traceback_msg,
    )

    return JSONResponse(
        {
            "status": 500,
            "detail": formatted,
            "traceback": traceback_msg,
        },
        status_code=500,
    )


def handle_exception_group(exc: ExceptionGroup) -> JSONResponse:
    # Collect info outside the except* block
    messages = []
    for e in exc.exceptions:
        if isinstance(e, BaseException):
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            nx.log.error(f"{e.__class__.__name__} - {e}\n{tb}")
            messages.append(f"{e.__class__.__name__}: {e!s}")
        else:
            messages.append(f"Non-standard exception: {e!r}")

    return JSONResponse(
        {
            "status": 500,
            "detail": f"ExceptionGroup: {len(exc.exceptions)} exceptions",
            "traceback": messages,
        },
        status_code=500,
    )


def req_id() -> str:
    return ShortUUID().random(length=16)


class BubblewrapMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = req_id()
        context = {"request_id": request_id}
        path = request.url.path

        with nx.log.contextualize(**context):
            start_time = time.perf_counter()
            try:
                response = await call_next(request)
            except BaseNXError as exc:
                response = handle_nx_exception(exc)
            except ExceptionGroup as eg:
                response = handle_exception_group(eg)
            except Exception as e:
                response = handle_undhandled_exception(e)
            finally:
                process_time = round(time.perf_counter() - start_time, 3)
                f_result = f"| {response.status_code} in {process_time}s"
                nx.log.debug(f"[{request.method}] {path} {f_result}")

        return response
