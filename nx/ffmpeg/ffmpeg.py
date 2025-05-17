import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..exceptions import BaseNXError
from ..logging import logger


class FFmpegError(BaseNXError):
    pass


class FFmpegAbortedError(FFmpegError):
    pass


@dataclass
class FFmpegProgress:
    speed: float = 0.0
    position: float = 0.0


BASE_FFMPEG_CMD = [
    "ffmpeg",
    "-y",
    "-hide_banner",
    "-loglevel",
    "error",
    "-progress",
    "pipe:2",
]


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


async def ffmpeg(
    cmd: list[str],
    progress_handler: Callable[[FFmpegProgress], Awaitable[None]] | None = None,
    custom_handlers: list[Callable[[str], Awaitable[None]]] | None = None,
    check_abort: Callable[[], Awaitable[bool]] | None = None,
) -> None:
    progress = FFmpegProgress()
    progress_changed: bool = False
    return_code: int | None = None

    fflog: list[str] = []
    
    def write_log(line: str) -> None:
        fflog.append(line)
        if len(fflog) > 100:
            fflog.pop(0)
        logger.trace(line)

    #
    # Create ffmpeg command
    #

    full_cmd = BASE_FFMPEG_CMD + cmd
    logger.debug(f"{' '.join(full_cmd)}")
    process = await asyncio.create_subprocess_exec(
        *full_cmd,
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
            assert process.stderr is not None
            progress_changed = False
            line_b = await process.stderr.readline()
            if not line_b:
                break
            try:
                line = line_b.decode("utf-8").strip()
            except Exception:
                continue

            if progress_handler:
                match = re.search(r"speed=(\d+\.\d+)", line)
                if match:
                    progress.speed = float(match.group(1))

                match = re.search(r"out_time_ms=(\d+)", line)
                if match:
                    progress.position = float(match.group(1)) / 1_000_000
                    progress_changed = True

                if progress_changed:
                    await progress_handler(progress)

            for handler in custom_handlers or []:
                await handler(line)

            write_log(line)


        await process.wait()

        if process.returncode != 0:
            return_code = process.returncode

    finally:
        if abort_task:
            abort_task.cancel()
            try:
                await abort_task
            except asyncio.CancelledError:
                pass

    if check_abort and await check_abort():
        raise FFmpegAbortedError("FFmpeg process was aborted by the user")

    if return_code:
        message = fflog[-1] if fflog else "No log available"
        if fflog:
            full_log = "\n".join(fflog)
            message += f"\n\n{full_log}"

        raise FFmpegError(message)
