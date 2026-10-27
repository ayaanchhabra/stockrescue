import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  (registers tables)
from app.api import experiments, health, inventory, qloo
from app.config import settings
from app.db.session import Base, engine
from app.errors import InvalidTransition, NeedsResolution, NotFound
from app.services.experiment_calc import CalcError
from app.services.qloo_service import QlooError

log = logging.getLogger("stockrescue")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Hackathon shortcut. Replace with Alembic migrations before production use.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="StockRescue API", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                   allow_methods=["*"], allow_headers=["*"])

QLOO_HTTP = {"not_configured": 503, "auth": 502, "timeout": 504, "rate_limited": 429,
             "upstream": 502, "bad_response": 502}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


@app.exception_handler(QlooError)
async def _qloo(_: Request, e: QlooError):
    return _err(QLOO_HTTP.get(e.kind, 502), f"qloo_{e.kind}", str(e))


@app.exception_handler(NotFound)
async def _nf(_: Request, e: NotFound):
    return _err(404, "not_found", str(e))


@app.exception_handler(InvalidTransition)
async def _it(_: Request, e: InvalidTransition):
    return _err(409, "invalid_state", str(e))


@app.exception_handler(NeedsResolution)
async def _nr(_: Request, e: NeedsResolution):
    return _err(409, "needs_resolution", str(e))


@app.exception_handler(CalcError)
async def _ce(_: Request, e: CalcError):
    return _err(422, "invalid_calculation_input", str(e))


@app.exception_handler(Exception)
async def _unhandled(_: Request, e: Exception):
    log.exception("Unhandled error")  # stack trace goes to logs, not to the user
    return _err(500, "internal_error", "Something went wrong on our side.")


app.include_router(health.router)
app.include_router(qloo.router)
app.include_router(experiments.router)
app.include_router(inventory.router)