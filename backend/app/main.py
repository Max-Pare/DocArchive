import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.rate_limit import limiter
from app.routers import auth, catalog, documents
from app.storage import tighten_permissions

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Files written before the modes were tightened keep their old 0644/0755 until
    # something changes them, and that "something" has to run on every boot to cover
    # an archive that already exists. Idempotent, and it only touches what is wrong.
    changed = tighten_permissions()
    if changed:
        logger.warning("tightened permissions on %s existing path(s) under STORAGE_DIR", changed)
    yield


app = FastAPI(title="DocArchive API", version="1.0.0", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(documents.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
