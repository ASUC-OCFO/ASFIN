from fastapi import APIRouter

from ASFINT.Config.Config import PROCESS_TYPES

router = APIRouter(tags=["process-types"])


@router.get("/api/v1/process-types")
def get_process_types():
    """Returns all valid process types directly from ASFINT — never hardcoded."""
    return {"process_types": list(PROCESS_TYPES.keys())}
