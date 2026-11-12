from __future__ import annotations

import json

from fastapi import APIRouter

from tmon.api.schemas import RankingOut
from tmon.core.config import get_settings
from tmon.storage.objectstore import get_object_store
from tmon.tools.v2_ranking import KEY

router = APIRouter(tags=["ranking"])


@router.get("/v2/ranking", response_model=RankingOut)
def ranking() -> RankingOut:
    """Latest ranking of the liquid basket written by ``python -m tmon.tools.v2_ranking``,
    with the evidence per horizon and the gate verdicts. Not a recommendation unless
    ``recommendation_allowed`` is true."""
    try:
        data = get_object_store().get(get_settings().minio_artifact_bucket, KEY)
    except (FileNotFoundError, KeyError, OSError):
        return RankingOut(available=False)
    return RankingOut(available=True, **json.loads(data))
