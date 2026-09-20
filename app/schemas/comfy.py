from typing import Any

from app.schemas.common import StrictBaseModel


class ComfyVersionFetchRequest(StrictBaseModel):
    ref: str


class ComfyVersionUseRequest(StrictBaseModel):
    name: str


class ComfyModelDownloadRequest(StrictBaseModel):
    repo_id: str
    filename: str | None = None
    target: str = "checkpoints"


class ComfyDictResponse(StrictBaseModel):
    data: dict[str, Any]


class ComfyListResponse(StrictBaseModel):
    items: list[dict[str, Any]]


class ComfyLogResponse(StrictBaseModel):
    text: str

