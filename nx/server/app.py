__all__ = ["app"]

from fastapi import FastAPI

import nx

# from nx.server.gatekeeper import GatekeeperMiddleware
from nx.server.bubblewrap import BubblewrapMiddleware
from nx.server.lifespan import lifespan
from nx.version import __version__

nx.initialize()

app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url="/docs",
    title="Hyperballad",
    description="",
    version=__version__,
)

app.add_middleware(BubblewrapMiddleware)
# app.add_middleware(LoggingMiddleware)
# app.add_middleware(GatekeeperMiddleware)


@app.get("/")
async def root():
    raise ValueError("i am not here")
    return "i am not here"
