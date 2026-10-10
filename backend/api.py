from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import API_PREFIX, get_cors_origins, get_database_url
from database import create_engine, create_sessionmaker, init_db
from routers import game, health, leaderboard, users


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_engine(database_url or get_database_url())
        await init_db(engine)
        app.state.sessionmaker = create_sessionmaker(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="WeFit Game API", version="1.0.0", lifespan=lifespan)

    origins = get_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (health, game, users, leaderboard):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
