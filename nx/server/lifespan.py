from contextlib import asynccontextmanager

from fastapi import FastAPI

import nx


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app

    nx.log.success("Server started")

    yield

    nx.log.info("Stopping server...")
