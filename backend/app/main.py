import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  (registers tables)
from app.api import experiments, health, qloo , rescue , inventory
from app.config import settings
from app.db.session import Base, engine
from app.errors import InvalidTransition, NeedsResolution, NotFound, StockCommitmentConflict
from app.services.experiment_calc import CalcError
from app.services.qloo_service import QlooError
from app.security import (SecurityConfigurationError, authenticate_bearer,
                           rate_limiter)

log = logging.getLogger("stockrescue")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Hackathon shortcut. Replace with Alembic migrations before production use.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="StockRescue API", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                   expose_headers=["X-Rescue-Plan-Id"])

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




@app.exception_handler(StockCommitmentConflict)
async def _stock_conflict(_: Request, e: StockCommitmentConflict):
    return JSONResponse(status_code=409, content={
        "error": "stock_commitment_conflict",
        "message": str(e),
        "conflicting_skus": e.skus,
    })


@app.exception_handler(CalcError)
async def _ce(_: Request, e: CalcError):
    return _err(422, "invalid_calculation_input", str(e))


@app.exception_handler(Exception)
async def _unhandled(_: Request, e: Exception):
    log.exception("Unhandled error")  # stack trace goes to logs, not to the user
    return _err(500, "internal_error", "Something went wrong on our side.")


@app.middleware("http")
async def authenticate_and_limit(request: Request, call_next):
    """Protect every API path except liveness/docs; assign tenant from token only."""
    path = request.url.path
    public_paths = {"/health", "/docs", "/openapi.json", "/redoc"}
    if request.method == "OPTIONS" or path in public_paths:
        return await call_next(request)

    try:
        retailer_id = authenticate_bearer(request.headers.get("authorization"))
    except SecurityConfigurationError:
        return _err(503, "auth_not_configured",
                    "API authentication is not configured; set retailer token hashes before serving API traffic.")
    if retailer_id is None:
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={"error": "unauthorized", "message": "A valid retailer bearer token is required."},
        )
    request.state.retailer_id = retailer_id

    # Only quota-consuming routes are throttled. The limiter is per process;
    # the Render deployment must remain single-worker until a shared limiter exists.
    limit_key = None
    limit = None
    if (path in {"/qloo/status", "/qloo/search"}
            or (path.startswith("/products/") and "/qloo/" in path
                and path.rsplit("/", 1)[-1] in {"resolve", "insights"})):
        limit_key, limit = (retailer_id, "qloo"), settings.qloo_requests_per_minute
    elif path.startswith("/rescue/") and path.rsplit("/", 1)[-1].isdigit() and request.method == "POST":
        limit_key, limit = (retailer_id, "rescue"), settings.rescue_runs_per_minute
    if limit_key and not rate_limiter.allow(limit_key, limit or 1):
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60"},
            content={"error": "rate_limited", "message": "Request limit reached. Retry in 60 seconds."},
        )
    return await call_next(request)


app.include_router(health.router)
app.include_router(qloo.router)
app.include_router(experiments.router)
app.include_router(inventory.router)
app.include_router(rescue.router)
