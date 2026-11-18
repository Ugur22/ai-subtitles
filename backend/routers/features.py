"""
Feature flags exposed to the frontend (UI visibility only; routes enforce their own flags).
"""
from typing import Dict

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from middleware.auth import require_auth
from services.feature_flags import all_flags

router = APIRouter(prefix="/api/features", tags=["Features"])


@router.get("", response_model=Dict[str, bool])
@require_auth
async def get_features(request: Request) -> Dict[str, bool]:
    return await run_in_threadpool(all_flags)
