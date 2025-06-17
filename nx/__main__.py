"""nx cli
======

This entrypoint is used to run nx in a development environment.
It is used to test various features of nx and to run the vanilla server
without any modifications.

It is not intended to be used in production.
"""

import asyncio
import os
import signal
import subprocess
import sys
from typing import Any

import nx
from nx.version import __version__

nx.initialize(standalone=True)


GUNICORN_PID_FILE = "/tmp/gunicorn.pid"  # noqa: S108


def version() -> None:
    """Show the version."""
    print(__version__, end="")  # noqa: T201


def run(*args: Any) -> None:
    """Run a command."""
    nx.log.info(f"Running command, {args}")


def serve() -> None:
    """Run the server."""
    cmd = [
        "gunicorn",
        "--bind",
        f":{nx.config.server_port}",
        "--reload",
        "--worker-class",
        "uvicorn_worker.UvicornWorker",
        "--max-requests",
        "1000",
        "--log-level",
        "warning",
        "--pid",
        GUNICORN_PID_FILE,
        "nx.server.app:app",
    ]

    process = subprocess.Popen(cmd)  # noqa: S603
    gunicorn_pid = process.pid

    def handle_sigterm(signum, frame) -> None:  # type: ignore[no-untyped-def]
        _ = signum, frame
        nx.log.warning("Received SIGTERM")
        os.kill(gunicorn_pid, signal.SIGTERM)

    def handle_sigint(signum, frame) -> None:  # type: ignore[no-untyped-def]
        _ = signum, frame
        nx.log.warning("Received SIGINT")
        os.kill(gunicorn_pid, signal.SIGINT)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigint)

    process.wait()
    nx.log.info("Gunicorn process terminated.")


def reload() -> None:
    """Reload the server by sending SIGHUP to Gunicorn."""
    if os.path.exists(GUNICORN_PID_FILE):
        with open(GUNICORN_PID_FILE) as f:
            try:
                gunicorn_pid = int(f.read().strip())
                os.kill(gunicorn_pid, signal.SIGHUP)
                nx.log.info(f"Sent SIGHUP to Gunicorn (PID: {gunicorn_pid}).")
            except ValueError:
                nx.log.error("Invalid PID in Gunicorn PID file.")
            except ProcessLookupError:
                nx.log.error("Gunicorn process not found.")
    else:
        nx.log.error("Gunicorn PID file not found.")


async def debug() -> None:
    print(nx.config.model_dump_json(indent=2, exclude_unset=True))  # noqa: T201
    res = await nx.db.fetch("SELECT * FROM config")
    print(res)  # noqa: T201


if __name__ == "__main__":
    if "version" in sys.argv:
        version()
    elif "run" in sys.argv:
        run(sys.argv[2:])
    elif "serve" in sys.argv:
        serve()
    elif "reload" in sys.argv:
        reload()
    elif "debug" in sys.argv:
        asyncio.run(debug())
    else:
        nx.log.error("Invalid command. Use 'version', 'run', 'serve', or 'reload'.")
        sys.exit(1)
