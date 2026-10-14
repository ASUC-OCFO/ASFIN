from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import datasets, ingestions, process_types, publish
from app.core.database import check_connection, engine
from app.core.models import Base

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="ASFINT Data Platform", lifespan=lifespan)

app.include_router(datasets.router)
app.include_router(ingestions.router)
app.include_router(process_types.router)
app.include_router(publish.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    """Liveness check. Returns 200 if the API process is running."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness check. Returns 503 if the database is unreachable."""
    if check_connection():
        return {"status": "ok", "database": "reachable"}
    return JSONResponse(
        status_code=503,
        content={"status": "unavailable", "database": "unreachable"},
    )
