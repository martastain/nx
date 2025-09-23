import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import IO, Any

from nx.exceptions import BaseNXError
from nx.logging import logger


class FFmpegError(BaseNXError):
    pass


class FFmpegAbortedError(FFmpegError):
    pass


class EndOfStreamError(FFmpegError):
    pass


@dataclass
class FFmpegProgress:
    speed: float = 0.0
    position: float = 0.0


BASE_FFMPEG_CMD = ["ffmpeg", "-y", "-hide_banner", "-progress", "pipe:2"]


async def abort_watcher(
    process: asyncio.subprocess.Process,
    check_abort: Callable[[], Awaitable[bool]],
) -> None:
    while True:
        await asyncio.sleep(1)
        if await check_abort():
            logger.warning("[AbortWatcher] Aborting FFmpeg!")
            process.terminate()  # or use `kill()` if needed
            return


async def cancel_task_if_needed(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class FFLog:
    """Simple fifo log for ffmpeg process

    This is used to capture last lines of the ffmpeg process
    stderr output in case of an error.
    """

    def __init__(self) -> None:
        self._log: list[str] = []
        self._max_size = 30

    def add(self, line: str) -> None:
        self._log.append(line)
        if len(self._log) > self._max_size:
            self._log.pop(0)

    def get_error_message(self) -> str:
        if not self._log:
            return "No log available"
        message = self._log[-1]
        if len(self._log) == 1:
            return message
        full_log = "\n".join(self._log)
        message += f"\n\n{full_log}"
        return message


async def get_stderr_line(process: asyncio.subprocess.Process) -> str:
    """Return a line from the stderr of the process.

    - Line is returned as a string.
    - At the end of the stream, an EndOfStreamError is raised.
    - If the line cannot be decoded, a ValueError is raised.
    """
    assert process.stderr is not None
    line_b = await process.stderr.readline()
    if not line_b:
        raise EndOfStreamError("FFmpeg process ended unexpectedly")
    try:
        line = line_b.decode("utf-8").strip()
    except Exception as e:
        raise ValueError(f"Failed to decode line: {e}") from e
    return line


def update_progress_object(progress: FFmpegProgress, line: str) -> bool:
    progress_changed = False
    match = re.search(r"out_time_ms=(\d+)", line)
    if match:
        progress.position = float(match.group(1)) / 1_000_000
        progress_changed = True

    match = re.search(r"speed=(\d+\.\d+)", line)
    if match:
        progress.speed = float(match.group(1))

    return progress_changed


async def ffmpeg(  # noqa: C901, PLR0913
    cmd: list[str],
    progress_handler: Callable[[FFmpegProgress], Awaitable[None]] | None = None,
    custom_handlers: list[Callable[[str], Awaitable[None]]] | None = None,
    check_abort: Callable[[], Awaitable[bool]] | None = None,
    niceness: int | None = None,
    taskset: str | None = None,
    stdin: int | IO[Any] | None = None,
) -> None:
    progress = FFmpegProgress()
    fflog = FFLog()

    #
    # Create ffmpeg command
    #

    pre_cmd: list[str] = []

    if niceness is not None:
        pre_cmd.extend(["nice", f"-n{niceness}"])

    if taskset is not None:
        pre_cmd.extend(["taskset", taskset])

    full_cmd = pre_cmd + BASE_FFMPEG_CMD + cmd
    logger.debug(f"{' '.join(full_cmd)}")
    process = await asyncio.create_subprocess_exec(
        *full_cmd,
        stdin=stdin,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    #
    # Create abort controller
    #

    abort_task: asyncio.Task[None] | None = None

    if check_abort:
        abort_task = asyncio.create_task(abort_watcher(process, check_abort))

    try:
        while True:
            try:
                line = await get_stderr_line(process)
            except EndOfStreamError:
                break
            except ValueError:
                continue

            fflog.add(line)

            for handler in custom_handlers or []:
                await handler(line)

            if not progress_handler:
                continue

            if update_progress_object(progress, line):
                await progress_handler(progress)

        await process.wait()

    finally:
        await cancel_task_if_needed(abort_task)

    if check_abort and await check_abort():
        raise FFmpegAbortedError("FFmpeg process was aborted by the user")

    if process.returncode:
        raise FFmpegError(fflog.get_error_message())
