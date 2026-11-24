import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import check_db_readiness
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="scout", version="0.1.0")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    try:
        database_ready, vector_ready = await check_db_readiness()
    except SQLAlchemyError:
        logger.exception("Database readiness check failed")
        database_ready, vector_ready = False, False
    if not database_ready or not vector_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(
                status="degraded",
                database=database_ready,
                vector_extension=vector_ready,
            ).model_dump(),
        )
    return ReadinessResponse(status="ready", database=True, vector_extension=True)
